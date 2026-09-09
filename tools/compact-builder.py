#!/usr/bin/env python3
"""Compact only the stopped, file-backed Apex builder after explicit authorization."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
from apexlib.common import Blocked, atomic_json, config, regular_file, sha256, state_dir
from apexlib.vm import alive, validate_disk


def identity(path):
    st = path.stat()
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_nlink]


def validate_info(chain):
    if not chain or chain[0]['format'] != 'qcow2':
        raise Blocked('Expected a QCOW2 builder')
    for item in chain:
        extra = item.get('format-specific', {}).get('data', {})
        if item.get('snapshots') or extra.get('bitmaps') or extra.get('corrupt') or item.get('dirty-flag'):
            raise Blocked('Preserve snapshots/bitmaps or repair corruption before compaction')


def validate_retained(report, source, target):
    if (report.get('source') != str(source) or report.get('replacement') != 'NOT PERFORMED'
            or report.get('error') != 'Validated copy does not save enough space; original retained'):
        raise Blocked('Only a retained copy blocked by insufficient savings can be resumed')
    for key in ('source_sha256', 'compressed_sha256'):
        if not re.fullmatch('[a-f0-9]{64}', report.get(key, '')):
            raise Blocked('Retained compaction is missing its complete file hashes')
    comparisons = [c for c in report.get('commands', []) if c.get('argv') ==
                   ['qemu-img', 'compare', '-f', 'qcow2', '-F', 'qcow2', str(source), str(target)]]
    if len(comparisons) != 1 or comparisons[0].get('returncode') != 0:
        raise Blocked('Retained copy lacks a successful full guest-data comparison')


def projected_free(r, source):
    projected = shutil.disk_usage(r).free + source.stat().st_blocks * 512
    if projected < config()['builder']['minimum_free_gib'] * 1024**3:
        raise Blocked('Projected free space remains below the builder startup threshold')
    return projected


def resume_compaction(r, source, run_id):
    if not re.fullmatch('[a-f0-9]{32}', run_id):
        raise Blocked('Invalid retained compaction ID')
    previous_dir = r / 'compactions' / run_id
    previous_path = regular_file(previous_dir / 'result.json', within=r)
    previous = json.loads(previous_path.read_text())
    target = regular_file(previous_dir / 'builder-compressed.qcow2', within=r)
    validate_retained(previous, source, target)
    if target.stat().st_nlink != 1 or source.stat().st_dev != target.stat().st_dev:
        raise Blocked('The retained copy needs one link on the builder filesystem')
    projected_free(r, source)
    destination = previous_dir / ('finalize-' + uuid.uuid4().hex)
    destination.mkdir(mode=0o700)
    shutil.copyfile(Path(__file__), destination / 'compact-builder.py')
    report = {'status': 'BLOCKED', 'phase': 'validating retained copy', 'source': str(source),
              'target': str(target), 'replacement': 'NOT PERFORMED', 'commands': [],
              'previous_report_sha256': sha256(previous_path), 'previous_run': run_id}
    def save():
        atomic_json(destination / 'result.json', report)
    def command(args):
        p = subprocess.run(list(map(str, args)), text=True, capture_output=True)
        report['commands'].append({'argv': list(map(str, args)), 'returncode': p.returncode,
                                   'stdout': p.stdout, 'stderr': p.stderr})
        save()
        if p.returncode:
            raise Blocked('Retained-copy validation failed; no replacement performed')
        return p.stdout
    print(destination, flush=True)
    try:
        chain = json.loads(command(['qemu-img', 'info', '--output=json', '--backing-chain', source]))
        validate_info(chain)
        paths = [regular_file(Path(item['filename']), within=r) for item in chain]
        identities = {str(path): identity(path) for path in paths}
        if identities != previous['before']['identity']:
            raise Blocked('Original builder chain changed since compaction')
        target_identity = identity(target)
        after = json.loads(command(['qemu-img', 'info', '--output=json', target]))
        validate_info([after])
        if after.get('backing-filename') or after['virtual-size'] != chain[0]['virtual-size']:
            raise Blocked('Retained copy must be standalone with unchanged virtual capacity')
        report['phase'] = 'hashing original and retained copy'
        save()
        for name, path in [('source_sha256', source), ('compressed_sha256', target)]:
            report[name] = sha256(path)
            save()
            if report[name] != previous[name]:
                raise Blocked('File content changed since compaction')
        for path in paths + [target]:
            command(['qemu-img', 'check', '--output=json', path])
        report['phase'] = 'comparing complete guest data'
        save()
        command(['qemu-img', 'compare', '-f', 'qcow2', '-F', 'qcow2', source, target])
        if (alive(r) or identities != {str(path): identity(path) for path in paths}
                or target_identity != identity(target)):
            raise Blocked('VM or image identity changed during finalization')
        os.chmod(target, source.stat().st_mode & 0o777)
        with target.open('rb') as stream:
            os.fsync(stream.fileno())
        report['projected_free'] = projected_free(r, source)
        report['replacement'] = 'VALIDATED, PENDING ATOMIC REPLACE'
        report['phase'] = 'replacing validated builder file'
        save()
        os.replace(target, source)
        report['replacement'] = 'COMPLETE'
        for parent in (r, previous_dir):
            fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        report['free_after'] = shutil.disk_usage(r).free
        report['status'] = 'PASS'
        report['phase'] = 'complete'
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--replace-verified', action='store_true', required=True,
                        help='Authorize replacing only builder.qcow2 after complete validation')
    parser.add_argument('--resume', metavar='COMPACTION_ID',
                        help='Revalidate and reuse an existing copy; do not convert again')
    args = parser.parse_args()
    r = state_dir()
    with (r / 'build.lock').open('a') as build_lock, (r / 'vm.lock').open('a') as vm_lock:
        for lock in (build_lock, vm_lock):
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if alive(r):
            raise Blocked('All Apex VMs must be stopped')
        source = regular_file(r / 'builder.qcow2', within=r)
        if source.stat().st_nlink != 1:
            raise Blocked('Builder must have exactly one filesystem link')
        validate_disk(source, r)
        if args.resume:
            return resume_compaction(r, source, args.resume)
        destination = r / 'compactions' / uuid.uuid4().hex
        destination.mkdir(parents=True, mode=0o700)
        target = destination / 'builder-compressed.qcow2'
        report = {'status': 'FAIL', 'source': str(source), 'replacement': 'NOT PERFORMED', 'commands': []}
        def save():
            atomic_json(destination / 'result.json', report)
        def command(args):
            p = subprocess.run(list(map(str, args)), text=True, capture_output=True)
            report['commands'].append({'argv': list(map(str, args)), 'returncode': p.returncode,
                                       'stdout': p.stdout, 'stderr': p.stderr})
            save()
            if p.returncode:
                raise Blocked('Compaction validation failed; original retained')
            return p.stdout
        print(destination, flush=True)
        try:
            report['version'] = command(['qemu-img', '--version'])
            chain = json.loads(command(['qemu-img', 'info', '--output=json', '--backing-chain', source]))
            validate_info(chain)
            paths = [regular_file(Path(item['filename']), within=r) for item in chain]
            identities = {str(path): identity(path) for path in paths}
            report['before'] = {'chain': chain, 'identity': identities, 'free': shutil.disk_usage(r).free}
            if shutil.disk_usage(r).free < source.stat().st_blocks * 512 + 4 * 1024**3:
                raise Blocked('Not enough room for a separate compressed copy and reserve')
            for path in paths:
                command(['qemu-img', 'check', '--output=json', path])
            report['source_sha256'] = sha256(source)
            save()
            args = ['qemu-img', 'convert', '-f', 'qcow2', '-O', 'qcow2', '-c',
                    '-o', 'compression_type=zstd', '-m', '2', str(source), str(target)]
            with (destination / 'convert.log').open('wb') as log:
                p = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
                try:
                    while p.poll() is None:
                        if shutil.disk_usage(r).free < 12 * 1024**3:
                            p.terminate()
                            p.wait(timeout=30)
                            raise Blocked('Compaction stopped to preserve 12 GiB free; original retained')
                        time.sleep(2)
                finally:
                    if p.poll() is None:
                        p.terminate()
                        p.wait(timeout=30)
            report['commands'].append({'argv': args, 'returncode': p.returncode})
            save()
            if p.returncode:
                raise Blocked('Conversion failed; original and partial output retained')
            after = json.loads(command(['qemu-img', 'info', '--output=json', target]))
            validate_info([after])
            if after.get('backing-filename') or after['virtual-size'] != chain[0]['virtual-size']:
                raise Blocked('Expected a standalone copy with identical virtual capacity')
            command(['qemu-img', 'check', '--output=json', target])
            command(['qemu-img', 'compare', '-f', 'qcow2', '-F', 'qcow2', source, target])
            if alive(r) or identities != {str(path): identity(path) for path in paths}:
                raise Blocked('Source or VM state changed during compaction')
            projected = shutil.disk_usage(r).free + source.stat().st_blocks * 512
            minimum = config()['builder']['minimum_free_gib'] * 1024**3
            report['after'] = after
            report['projected_free'] = projected
            report['compressed_sha256'] = sha256(target)
            if projected < minimum:
                raise Blocked('Validated copy does not save enough space; original retained')
            os.chmod(target, source.stat().st_mode & 0o777)
            with target.open('rb') as stream:
                os.fsync(stream.fileno())
            report['replacement'] = 'VALIDATED, PENDING ATOMIC REPLACE'
            save()
            # The authorized original container is replaced only after full equality.
            # Its guest data remains in the validated copy; its old QCOW2 layout is not kept.
            os.replace(target, source)
            fd = os.open(r, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            report['replacement'] = 'COMPLETE'
            report['free_after'] = shutil.disk_usage(r).free
            report['status'] = 'PASS'
        except Exception as error:
            report['error'] = str(error)
            raise
        finally:
            save()


if __name__ == '__main__':
    main()

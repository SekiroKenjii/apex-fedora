#!/usr/bin/python3
"""Prepare file-backed multiboot media inside the isolated builder only."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_inputs(work, request):
    if set(request['files']) != {'ventoy.tar.gz', 'Apex-Live.iso', 'Ubuntu.iso'}:
        raise RuntimeError('Expected exactly the reviewed Ventoy and two ISO inputs')
    for name, checksum in request['files'].items():
        path = work / name
        if (not re.fullmatch('[a-f0-9]{64}', checksum) or path.is_symlink()
                or not path.is_file() or digest(path) != checksum):
            raise RuntimeError(f'Input checksum mismatch: {name}')
    if not re.fullmatch(r'\d+\.\d+\.\d+', request['ventoy_version']):
        raise RuntimeError('Invalid Ventoy version')


def verify_loop(loop, raw):
    if not re.fullmatch(r'/dev/loop[0-9]+', loop):
        raise RuntimeError('Expected a newly allocated loop device')
    backing = Path('/sys/class/block') / Path(loop).name / 'loop/backing_file'
    if (not Path(loop).is_block_device()
            or Path(backing.read_text().strip()).resolve() != raw.resolve()):
        raise RuntimeError('Loop device does not belong to this new file')


def main():
    if (os.geteuid() != 0 or Path('/etc/apex-builder').read_text().strip() != 'apex-isolated-builder-v1'
            or run('systemd-detect-virt', '--vm', capture_output=True, text=True).stdout.strip() not in {'kvm', 'qemu'}):
        raise RuntimeError('Media preparation requires the isolated builder VM')
    work = Path.cwd()
    if work.parent != Path('/var/tmp') or not re.fullmatch('apex-ventoy-[a-f0-9]{32}', work.name):
        raise RuntimeError('Use a new private builder work directory')
    request = json.loads((work / 'request.json').read_text())
    verify_inputs(work, request)
    if shutil.disk_usage(work).free < 27 * 1024**3:
        raise RuntimeError('Need 27 GiB free inside builder for raw and QCOW2 media')
    run('dnf5', '-y', 'install', 'parted', 'exfatprogs', 'qemu-img', 'util-linux', 'xz')
    extracted = work / 'upstream'
    extracted.mkdir(mode=0o700)
    with tarfile.open(work / 'ventoy.tar.gz') as archive:
        archive.extractall(extracted, filter='data')
    upstream = extracted / ('ventoy-' + request['ventoy_version'])
    if (upstream / 'ventoy/version').read_text().strip() != request['ventoy_version']:
        raise RuntimeError('Archive version differs from the reviewed request')
    raw = work / 'ventoy.raw'
    with raw.open('xb') as stream:
        stream.truncate(16 * 1024**3)
    loop = run('losetup', '--find', '--show', '--partscan', raw,
               capture_output=True, text=True).stdout.strip()
    mounted = False
    mount = work / 'mount'
    mount.mkdir()
    try:
        verify_loop(loop, raw)
        # No arbitrary device operand: only the loop returned for the new raw file.
        run('sh', 'Ventoy2Disk.sh', '-i', '-r', '2048', loop, cwd=upstream, input='y\ny\n', text=True)
        verify_loop(loop, raw)
        run('udevadm', 'settle', '--timeout=30')
        partition = Path(loop + 'p1')
        if not partition.is_block_device():
            raise RuntimeError('Ventoy data partition is missing')
        table = json.loads(run('sfdisk', '--json', loop, capture_output=True, text=True).stdout)
        if table['partitiontable']['label'] != 'dos' or len(table['partitiontable']['partitions']) != 2:
            raise RuntimeError('Unexpected Ventoy MBR layout')
        info = run('sh', 'Ventoy2Disk.sh', '-l', loop, cwd=upstream, capture_output=True, text=True).stdout
        if 'Ventoy Version in Disk: ' + request['ventoy_version'] not in info:
            raise RuntimeError('Installed Ventoy version does not match')
        run('mount', '-t', 'exfat', '-o', 'nosuid,nodev,noexec', partition, mount)
        mounted = True
        for name in ('Apex-Live.iso', 'Ubuntu.iso'):
            shutil.copyfile(work / name, mount / name)
            if digest(mount / name) != request['files'][name]:
                raise RuntimeError('ISO checksum changed on the virtual USB')
        os.sync()
        run('umount', mount)
        mounted = False
        run('fsck.exfat', '-n', partition)
    finally:
        if mounted:
            run('umount', mount)
        verify_loop(loop, raw)
        run('losetup', '--detach', loop)
    output = work / 'output'
    output.mkdir(mode=0o755)
    run('qemu-img', 'convert', '-f', 'raw', '-O', 'qcow2', raw, output / 'ventoy.qcow2')
    run('qemu-img', 'check', '-f', 'qcow2', output / 'ventoy.qcow2')
    report = {'status': 'PASS', 'request': request, 'partition_table': table,
              'ventoy_info': info, 'image_sha256': digest(output / 'ventoy.qcow2'),
              'virtual_size': 16 * 1024**3, 'reserved_unformatted_mib': 2048,
              'physical_media_accessed': False, 'boot_acceptance': 'NOT TESTED',
              'secure_boot_acceptance': 'NOT TESTED', 'retained_work': str(work),
              'tools': run('rpm', '-q', 'parted', 'exfatprogs', 'qemu-img', 'util-linux', 'xz', capture_output=True, text=True).stdout}
    (output / 'media.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()

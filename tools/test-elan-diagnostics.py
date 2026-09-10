#!/usr/bin/env python3
"""Test patched ELAN metadata helpers without loading libfprint or opening USB."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import uuid

sys.dont_write_bytecode = True
from apexlib.common import ROOT, atomic_json, regular_file, sha256, state_dir

SILENT = ('disabled', 'wrong-opt-in', 'debug-transfer', 'debug-messages', 'wrong-device', 'wrong-vendor')
EXCLUDED = ('image', 'other-command', 'wrong-endpoint', 'outgoing', 'zero', 'overlong',
            'wrong-expected', 'null-buffer', 'failed')
STATUS = ('status-0', 'status-85', 'status-175', 'status-255')
LINE = re.compile(r'apex-elan-v1 event=(probe|transfer-error) action=3 state=2 '
                  r'command=(pre-scan|image|other) expected=-?\d+ actual=-?\d+ '
                  r'status=(-?\d+) domain=[0-4] code=-?\d+')


def run(source_path):
    if os.geteuid() == 0:
        raise ValueError('Run metadata-only tests without root')
    source_path = regular_file(source_path)
    lock = json.loads((ROOT / 'config/elan-diagnostics.lock.json').read_text())
    source_hash = sha256(source_path)
    reviewed = next((item for item in lock['sources'] if item['sha256'] == source_hash), None)
    if reviewed is None:
        raise ValueError('ELAN source checksum mismatch; refusing to compile')
    patch = regular_file(ROOT / lock['patch'], within=ROOT)
    flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gio-2.0'], text=True))
    results = {}
    with tempfile.TemporaryDirectory(prefix='apex-elan-metadata-') as work:
        work = Path(work)
        target = work / 'libfprint/drivers/elan.c'
        target.parent.mkdir(parents=True)
        target.write_bytes(source_path.read_bytes())
        subprocess.run(['git', 'init', '-q'], cwd=work, check=True)
        subprocess.run(['git', 'add', '--', 'libfprint/drivers/elan.c'], cwd=work, check=True)
        subprocess.run(['git', 'apply', '--check', '--index', '-p1', str(patch)], cwd=work, check=True)
        subprocess.run(['patch', '--batch', '--fuzz=0', '--forward', '-p1', '-i', str(patch)], cwd=work, check=True)
        content = target.read_text()
        start = content.index('/* This opt-in diagnostic never prints')
        end = content.index('static void\nelan_cmd_done (', start)
        helpers = content[start:end]
        assert helpers.count('transfer->buffer[0]') == 1
        assert 'error->message' not in helpers
        assert content.count('apex_elan_trace_transfer (transfer, dev, error);') == 1
        assert content.count('apex_elan_emit (dev, ssm, "pre-scan-protocol", 1,') == 1
        program = work / 'harness.c'
        program.write_text((ROOT / 'tests/fixtures/elan-diagnostics-harness.c').read_text()
                           .replace('/* APEX_DIAGNOSTIC_HELPERS */', helpers))
        binary = work / 'harness'
        subprocess.run(['cc', '-std=c11', '-O0', '-Wall', '-Werror', '-Wno-unused-parameter',
                        str(program), '-o', str(binary), *flags], check=True)
        for case in (*SILENT, *EXCLUDED, *STATUS, 'budget'):
            output = subprocess.check_output([str(binary), case], text=True, timeout=5)
            lines = output.splitlines()
            if case in SILENT:
                assert not lines, case
            else:
                assert len(lines) == (16 if case == 'budget' else 1), case
                assert all(LINE.fullmatch(line) for line in lines), case
                assert 'PRIVATE_PAYLOAD_SENTINEL' not in output, case
                expected = int(case[7:]) if case in STATUS else -1
                assert all(int(LINE.fullmatch(line)[3]) == expected for line in lines), case
            results[case] = {'status': 'PASS', 'lines': lines}
        subprocess.run(['patch', '--batch', '--fuzz=0', '-R', '-p1', '-i', str(patch)], cwd=work, check=True)
        assert sha256(target) == source_hash
    return {'status': 'PASS', 'scope': 'extracted metadata helpers with synthetic transfers and invalid non-status buffers',
            'source': reviewed['label'], 'source_sha256': source_hash, 'patch_sha256': sha256(patch),
            'compiler': subprocess.check_output(['cc', '--version'], text=True).splitlines()[0],
            'gio_version': subprocess.check_output(['pkg-config', '--modversion', 'gio-2.0'], text=True).strip(),
            'cases': results, 'reverse_patch': 'PASS', 'git_apply_index_check': 'PASS', 'full_driver_build': 'NOT TESTED',
            'capture_state_machine': 'NOT TESTED', 'physical_sensor': 'NOT TESTED'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    report = run(args.source)
    destination = state_dir() / 'elan-diagnostics-tests' / uuid.uuid4().hex / 'results.json'
    atomic_json(destination, report)
    print(json.dumps({'status': report['status'], 'cases': len(report['cases']), 'report': str(destination)}))

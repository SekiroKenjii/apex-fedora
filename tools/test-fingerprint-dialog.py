#!/usr/bin/env python3
"""Compile extracted, checksum-pinned GNOME handlers with device-free test shims."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

sys.dont_write_bytecode = True
from apexlib.common import ROOT, atomic_json, regular_file, sha256, state_dir

HANDLERS = ('handle_enroll_signal', 'cancel_button_clicked_cb', 'cc_fingerprint_dialog_close_attempt')


def function(source, name):
    marker = '\nstatic void\n' + name + ' ('
    if source.count(marker) != 1:
        raise ValueError('Expected one pinned GNOME function')
    start = source.index(marker)
    brace = source.index('{', start)
    level = 1
    end = brace + 1
    while level:
        if source[end] == '{':
            level += 1
        elif source[end] == '}':
            level -= 1
        end += 1
    return source[start:end]


def run(source_path):
    if os.geteuid() == 0:
        raise ValueError('Run handler-only tests without root')
    lock = json.loads((ROOT / 'config/gnome-fingerprint.lock.json').read_text())
    source_path = regular_file(source_path)
    if sha256(source_path) != lock['source_sha256']:
        raise ValueError('GNOME source checksum mismatch; refusing to compile')
    patch = regular_file(ROOT / lock['patch'], within=ROOT)
    source = source_path.read_text()
    template = (ROOT / 'tests/fixtures/fingerprint-dialog-harness.c').read_text()
    results = {}
    with tempfile.TemporaryDirectory(prefix='apex-dialog-test-') as work:
        work = Path(work)
        target = work / 'panels/system/users/cc-fingerprint-dialog.c'
        target.parent.mkdir(parents=True)
        target.write_text(source)
        subprocess.run(['patch', '--batch', '--fuzz=0', '--forward', '-p1', '-i', str(patch)], cwd=work, check=True)
        for variant, content in [('upstream', source), ('patched', target.read_text())]:
            program = work / (variant + '.c')
            extracted = '\n'.join(function(content, name) for name in HANDLERS)
            program.write_text(template.replace('/* APEX_EXTRACTED_HANDLERS */', extracted))
            binary = work / variant
            subprocess.run(['cc', '-std=c11', '-O0', '-Wall', '-Werror', '-Wno-unused-parameter',
                            '-Wno-unused-function', str(program), '-o', str(binary)], check=True)
            results[variant] = {case: json.loads(subprocess.check_output([str(binary), case], text=True))
                                for case in ('disconnect', 'cancel', 'retry', 'complete', 'unknown-error', 'unclaimed')}
    before, after = results['upstream'], results['patched']
    if before['disconnect']['release_calls'] != 0 or before['cancel']['cancel_calls'] != 0:
        raise ValueError('Pinned upstream no longer reproduces the cleanup regression')
    for case in ('disconnect', 'cancel', 'retry', 'complete', 'unknown-error'):
        if after[case]['state_after_signal'] != 3 or after[case]['stop_calls'] != 1 or after[case]['release_calls'] != 1:
            raise ValueError('Patched handler lost Stop/Release cleanup')
    if after['cancel']['cancel_calls'] != 1 or after['unclaimed']['release_calls'] != 0:
        raise ValueError('Patched cancellation/unclaimed guard regression')
    return {'status': 'PASS', 'scope': 'extracted GNOME handlers with stubbed widgets and D-Bus calls',
            'version': lock['version'], 'source_sha256': lock['source_sha256'], 'patch_sha256': sha256(patch),
            'compiler': subprocess.check_output(['cc', '--version'], text=True).splitlines()[0],
            'cases': results, 'gtk_integration': 'NOT TESTED', 'daemon_disappearance': 'NOT TESTED',
            'fedora_rpm_build': 'NOT TESTED', 'physical_sensor': 'NOT TESTED'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    report = run(args.source)
    destination = state_dir() / 'fingerprint-dialog-tests' / uuid.uuid4().hex / 'results.json'
    atomic_json(destination, report)
    print(json.dumps(report, indent=2))
    print(destination)

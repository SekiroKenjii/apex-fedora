#!/usr/bin/env python3
"""Compile extracted, checksum-pinned GNOME handlers with device-free test shims."""
import argparse
import hashlib
import json
import os
import re
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

sys.dont_write_bytecode = True
from apexlib.common import ROOT, atomic_json, regular_file, sha256, state_dir

HANDLERS = ('handle_enroll_signal', 'enroll_stop_cb', 'enroll_stop', 'on_device_owner_changed',
            'cancel_button_clicked_cb', 'cc_fingerprint_dialog_close_attempt')
CASES = ('disconnect', 'cancel', 'retry', 'complete', 'unknown-error', 'unclaimed',
         'daemon-gone', 'daemon-present', 'stop-success', 'stop-error', 'cancel-twice', 'close-pending')


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
    source_hash = sha256(source_path)
    reviewed = next((item for item in lock['reviewed_sources'] if item['sha256'] == source_hash), None)
    if reviewed is None:
        raise ValueError('GNOME source checksum mismatch; refusing to compile')
    patch = regular_file(ROOT / lock['patch'], within=ROOT)
    source = source_path.read_text()
    template = (ROOT / 'tests/fixtures/fingerprint-dialog-harness.c').read_text()
    enum = re.search(r'typedef enum \{[^}]+\} DialogState;', source)
    if enum is None:
        raise ValueError('Missing pinned dialog state enum')
    flags = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'gio-2.0'], text=True))
    results = {}
    with tempfile.TemporaryDirectory(prefix='apex-dialog-test-') as work:
        work = Path(work)
        target = work / 'panels/system/users/cc-fingerprint-dialog.c'
        target.parent.mkdir(parents=True)
        target.write_text(source)
        subprocess.run(['patch', '--batch', '--fuzz=0', '--forward', '-p1', '-i', str(patch)], cwd=work, check=True)
        for variant, content in [('unpatched', source), ('patched', target.read_text())]:
            program = work / (variant + '.c')
            extracted = '\n'.join(function(content, name) for name in HANDLERS)
            program.write_text(template.replace('/* APEX_DIALOG_STATE */', enum.group())
                               .replace('/* APEX_EXTRACTED_HANDLERS */', extracted))
            binary = work / variant
            subprocess.run(['cc', '-std=c11', '-O0', '-Wall', '-Werror', '-Wno-unused-parameter',
                            '-Wno-unused-function', str(program), '-o', str(binary), *flags], check=True)
            results[variant] = {case: json.loads(subprocess.check_output([str(binary), case], text=True))
                                for case in CASES}
    before, after = results['unpatched'], results['patched']
    if before['disconnect']['release_calls'] != 0 or before['cancel']['cancel_calls'] != 0:
        raise ValueError('Pinned source no longer reproduces the cleanup regression')
    for case in ('disconnect', 'cancel', 'retry', 'complete', 'unknown-error'):
        if after[case]['state_after_signal'] != 68 or after[case]['stop_calls'] != 1 or after[case]['release_calls'] != 1:
            raise ValueError('Patched handler lost Stop/Release cleanup')
    if after['cancel']['cancel_calls'] != 1 or after['unclaimed']['release_calls'] != 0:
        raise ValueError('Patched cancellation/unclaimed guard regression')
    if after['daemon-gone']['claim_calls'] != 1 or after['daemon-gone']['release_calls'] != 0:
        raise ValueError('Daemon-loss path attempted stale cleanup or skipped reacquisition')
    if after['daemon-present']['claim_calls'] != 0 or after['daemon-present']['release_calls'] != 1:
        raise ValueError('Present owner incorrectly treated as lost')
    for case in ('stop-success', 'stop-error', 'cancel-twice'):
        if after[case]['state_after_callback'] != 4 or after[case]['stop_calls'] != 0 or after[case]['release_calls'] != 1:
            raise ValueError('Stop callback left stale enrollment state')
    if before['cancel-twice']['state_after_callback'] != 196 or after['cancel-twice']['cancelled_callback']:
        raise ValueError('Repeated-cancel regression was not reproduced and fixed')
    if not after['close-pending']['cancelled_callback'] or after['close-pending']['release_calls'] != 1:
        raise ValueError('Close did not cancel its pending callback and release')
    return {'status': 'PASS', 'scope': 'extracted GNOME handlers with stubbed widgets and D-Bus calls',
            'source': reviewed['label'], 'source_sha256': source_hash, 'patch_sha256': sha256(patch),
            'compiler': subprocess.check_output(['cc', '--version'], text=True).splitlines()[0],
            'gio_version': subprocess.check_output(['pkg-config', '--modversion', 'gio-2.0'], text=True).strip(),
            'cases': results, 'gtk_integration': 'NOT TESTED', 'daemon_disappearance': 'HANDLER ONLY',
            'async_scope': 'Controlled callback ordering with real GCancellable; no D-Bus, GTK object lifetime or threaded race test',
            'fedora_rpm_build': 'NOT TESTED', 'physical_sensor': 'NOT TESTED'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    args = parser.parse_args()
    report = run(args.source)
    destination = state_dir() / 'fingerprint-dialog-tests' / uuid.uuid4().hex / 'results.json'
    atomic_json(destination, report)
    print(json.dumps({'status': report['status'], 'cases_per_variant': len(CASES), 'report': str(destination)}))

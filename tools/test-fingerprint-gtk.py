"""Run complete GTK/D-Bus regression tests in the file-backed Fedora builder."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
from apexlib.common import ROOT, Blocked, atomic_json, sha256, state_dir
from apexlib.vm import ssh_args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build_id')
    args = parser.parse_args()
    if not re.fullmatch('[a-f0-9]{32}', args.build_id):
        raise Blocked('Expected a fingerprint RPM build ID')
    runtime = state_dir()
    connection = ssh_args(runtime)
    parent = runtime / 'fingerprint-rpm-builds' / args.build_id
    build = json.loads((parent / 'output/results.json').read_text())
    if build['status'] != 'PASS':
        raise Blocked('The RPM build did not pass')
    run_id = uuid.uuid4().hex
    export = runtime / 'fingerprint-gtk-tests' / run_id
    export.mkdir(parents=True, mode=0o700)
    remote = '/var/tmp/apex-fingerprint-gtk-' + run_id
    files = ['guest/fingerprint-gtk.py', 'guest/fingerprint-gtk.c', 'guest/fingerprint-gtk-service.py',
             'config/fingerprint-rpms.lock.json', 'rpms/patches/gnome-fingerprint-retain-claim.patch']
    inputs = {name: sha256(ROOT / name) for name in files}
    patch_hash = build['packages']['gnome-control-center']['patch_sha256']
    if inputs[files[-1]] != patch_hash:
        raise Blocked('Current patch differs from the built RPM')
    archive_name = 'gnome-control-center-50.4.tar.xz'
    archive = parent / 'output/gnome-control-center/sources' / archive_name
    inputs['inputs/' + archive_name] = sha256(archive)
    atomic_json(export / 'request.json', {'parent_build': args.build_id, 'inputs': inputs})
    scp = ['scp', '-i', str(runtime / 'builder_ed25519'), '-P', connection[4], '-o', 'IdentitiesOnly=yes',
           '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={runtime}/known_hosts']
    subprocess.run(connection + [f'mkdir -m 700 {remote} && mkdir {remote}/guest {remote}/config {remote}/rpms {remote}/rpms/patches {remote}/inputs'], check=True)
    for name in files:
        subprocess.run(scp + [str(ROOT / name), f'builder@127.0.0.1:{remote}/{name}'], check=True)
    subprocess.run(scp + [str(archive), f'builder@127.0.0.1:{remote}/inputs/{archive_name}'], check=True)
    subprocess.run(scp + [str(export / 'request.json'), f'builder@127.0.0.1:{remote}/request.json'], check=True)
    print(export, flush=True)
    with (export / 'execution.log').open('wb') as log:
        result = subprocess.run(connection + [f'cd {remote} && flock -n test.lock python3 guest/fingerprint-gtk.py'], stdout=log, stderr=subprocess.STDOUT)
    transfer = subprocess.run(scp + ['-r', f'builder@127.0.0.1:{remote}/output', str(export)], check=False)
    atomic_json(export / 'execution.json', {'returncode': result.returncode, 'transfer_returncode': transfer.returncode})
    if result.returncode or transfer.returncode:
        raise Blocked(f'GTK regression did not pass; see {export}')
    report = json.loads((export / 'output/results.json').read_text())
    if report['status'] != 'PASS' or report['inputs'] != inputs:
        raise Blocked('Invalid GTK regression report')
    for variant, cases in report['variants'].items():
        for name, case in cases.items():
            if sha256(export / 'output' / variant / name / 'dialog.log') != case['log_sha256']:
                raise Blocked('GTK test log checksum mismatch')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

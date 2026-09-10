"""Run the packaged-library smoke tests in the existing file-backed builder."""
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
    directory = state_dir()
    connection = ssh_args(directory)
    source = ROOT / 'guest/fingerprint-rpm-smoke.py'
    run_id = uuid.uuid4().hex
    export = directory / 'fingerprint-rpm-tests' / run_id
    export.mkdir(parents=True, mode=0o700)
    remote = f'/var/tmp/apex-fingerprint-rpm-tests-{run_id}'
    names = [f'{name}-1.94.100-1.fc44.apex1.x86_64.rpm' for name in ('libfprint', 'libfprint-tests')]
    prefix = f'/var/tmp/apex-fingerprint-rpms-{args.build_id}/output/libfprint/mock/'
    # The installed test stage has its own lock; Mock uses a separate RPM database.
    subprocess.run(connection + [f'mkdir -m 700 {remote} {remote}/inputs && cp ' + ' '.join(prefix + name for name in names) + f' {remote}/inputs/'], check=True)
    scp = ['scp', '-i', str(directory / 'builder_ed25519'), '-P', connection[4], '-o', 'IdentitiesOnly=yes',
           '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={directory}/known_hosts']
    subprocess.run(scp + [str(source), f'builder@127.0.0.1:{remote}/test.py'], check=True)
    subprocess.run(scp + ['-r', f'builder@127.0.0.1:{remote}/inputs', str(export)], check=True)
    inputs = {name: sha256(export / 'inputs' / name) for name in names}
    atomic_json(export / 'inputs.json', inputs)
    atomic_json(export / 'source.json', {'path': 'guest/fingerprint-rpm-smoke.py', 'sha256': sha256(source), 'parent_build': args.build_id})
    subprocess.run(scp + [str(export / 'inputs.json'), f'builder@127.0.0.1:{remote}/inputs.json'], check=True)
    print(export, flush=True)
    with (export / 'test.log').open('wb') as log:
        result = subprocess.run(connection + [f'cd {remote} && sudo flock -n /run/apex-fingerprint-test.lock python3 test.py'], stdout=log, stderr=subprocess.STDOUT)
    subprocess.run(connection + [f'sudo chown -R builder:builder {remote}/output'], check=False)
    transfer = subprocess.run(scp + ['-r', f'builder@127.0.0.1:{remote}/output', str(export)], check=False)
    atomic_json(export / 'execution.json', {'returncode': result.returncode, 'transfer_returncode': transfer.returncode})
    if result.returncode or transfer.returncode:
        raise Blocked(f'Packaged library tests failed; see {export}')
    report = json.loads((export / 'output/results.json').read_text())
    if (report.get('status') != 'PASS' or report.get('rpm_sha256') != inputs
            or set(report.get('cases', {})) != {'fpi-ssm', 'fpi-device'}
            or any(case.get('status') != 'PASS' for case in report['cases'].values())
            or report.get('hardware') != 'NOT TESTED'):
        raise Blocked('Incomplete packaged-library result')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()

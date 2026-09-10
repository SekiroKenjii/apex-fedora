"""Build fingerprint RPMs in the dedicated VM; do not modify an OS image."""
import fcntl
import json
from pathlib import Path
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
from apexlib.common import Blocked, atomic_json, regular_file, sha256, state_dir
from apexlib.pipeline import export_source
from apexlib.vm import ssh_args


def verify_report(out, manifest):
    report = json.loads(regular_file(out / 'results.json', within=out).read_text())
    if (report.get('status') != 'PASS' or report.get('stage') != 'rpm-build'
            or report.get('source_lock_sha256') != manifest['files']['config/fingerprint-rpms.lock.json']
            or report.get('ready_to_install') is not False
            or any(report.get(key) != 'NOT TESTED' for key in ('hardware', 'image_integration', 'full_gtk_dbus_integration'))):
        raise Blocked('Invalid RPM build result')
    expected = {'libfprint': 'rpms/patches/libfprint-elan-status-diagnostics.patch',
                'gnome-control-center': 'rpms/patches/gnome-fingerprint-retain-claim.patch'}
    if set(report.get('packages', {})) != set(expected):
        raise Blocked('Incomplete fingerprint package set')
    for name, patch in expected.items():
        entry = report['packages'][name]
        if entry.get('status') != 'PASS' or entry.get('patch_sha256') != manifest['files'][patch] or not entry.get('rpms'):
            raise Blocked('Built package does not match the requested patch')
        if any(f'{name}/mock/{rpm}' not in report.get('artifacts', {}) for rpm in entry['rpms']):
            raise Blocked('Built package is missing its RPM artifact')
    artifacts = report.get('artifacts', {})
    if not any(name.startswith('packages/repodata/') for name in artifacts):
        raise Blocked('Missing local RPM repository')
    for relative, expected_hash in artifacts.items():
        path = Path(relative)
        if path.is_absolute() or '..' in path.parts or sha256(regular_file(out / path, within=out)) != expected_hash:
            raise Blocked('Transferred RPM artifact checksum mismatch')
    return report


def main():
    directory = state_dir()
    with (directory / 'build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        connection = ssh_args(directory)
        run_id = uuid.uuid4().hex
        export = directory / 'fingerprint-rpm-builds' / run_id
        export.mkdir(parents=True, mode=0o700)
        manifest = export_source(export / 'source.tar')
        atomic_json(export / 'source-manifest.json', manifest)
        remote = f'/var/tmp/apex-fingerprint-rpms-{run_id}'
        subprocess.run(connection + [f'mkdir -m 700 {remote}'], check=True)
        scp = ['scp', '-i', str(directory / 'builder_ed25519'), '-P', connection[4],
               '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', f'UserKnownHostsFile={directory}/known_hosts']
        subprocess.run(scp + [str(export / 'source.tar'), f'builder@127.0.0.1:{remote}/'], check=True)
        print(export, flush=True)
        command = f'cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock python3 guest/fingerprint-rpms.py'
        with (export / 'build.log').open('wb') as log:
            result = subprocess.run(connection + [command], stdout=log, stderr=subprocess.STDOUT)
        subprocess.run(connection + [f'sudo chown -R builder:builder {remote}/output'], check=False)
        transfer = subprocess.run(scp + ['-r', f'builder@127.0.0.1:{remote}/output', str(export)], check=False)
        atomic_json(export / 'execution.json', {'returncode': result.returncode, 'transfer_returncode': transfer.returncode,
                                              'remote': remote, 'ready_to_install': False})
        if result.returncode or transfer.returncode:
            raise Blocked(f'Fingerprint RPM build failed; inspect {export}/build.log')
        out = export / 'output'
        report = verify_report(out, manifest)
        atomic_json(export / 'verified.json', {'status': 'PASS', 'artifacts': len(report['artifacts']),
                                             'results_sha256': sha256(out / 'results.json')})
        print('RPM build and transfer verified; image and hardware are NOT TESTED')


if __name__ == '__main__':
    main()

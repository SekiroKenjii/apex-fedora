"""Integrate tested fingerprint RPMs without rebuilding the frozen Fedora base."""
import argparse
import fcntl
import json
import re
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
from apexlib.common import ROOT, Blocked, atomic_json, sha256, state_dir
from apexlib.pipeline import export_source
from apexlib.signatures import verify
from apexlib.vm import ssh_args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('parent_build')
    parser.add_argument('rpm_build')
    parser.add_argument('gtk_test')
    args = parser.parse_args()
    if any(not re.fullmatch('[a-f0-9]{32}', value) for value in vars(args).values()):
        raise Blocked('Expected completed build/test IDs')
    runtime = state_dir()
    with (runtime / 'build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        parent = runtime / 'exports' / args.parent_build
        frozen = json.loads((parent / 'output/image.json').read_text())
        verified = verify(parent / 'output', runtime / 'trust/development.pub')
        if verified['digest'] != frozen['digest'] or frozen['profile'] != 'fedora':
            raise Blocked('Parent identity mismatch')
        gtk_dir = runtime / 'fingerprint-gtk-tests' / args.gtk_test
        gtk = json.loads((gtk_dir / 'output/results.json').read_text())
        if gtk['status'] != 'PASS' or not all(c['status'] == 'PASS' for c in gtk['variants']['patched'].values()):
            raise Blocked('Complete GTK tests must pass before image integration')
        for variant, cases in gtk['variants'].items():
            for name, case in cases.items():
                if sha256(gtk_dir / 'output' / variant / name / 'dialog.log') != case['log_sha256']:
                    raise Blocked('GTK test evidence changed')
        rpm_root = runtime / 'fingerprint-rpm-builds' / args.rpm_build / 'output'
        rpm_report = json.loads((rpm_root / 'results.json').read_text())
        if (rpm_report['status'] != 'PASS'
                or gtk['patch_sha256'] != rpm_report['packages']['gnome-control-center']['patch_sha256']
                or gtk['patch_sha256'] != sha256(ROOT / 'rpms/patches/gnome-fingerprint-retain-claim.patch')):
            raise Blocked('Tested patch differs from the built package')
        names = ['libfprint-1.94.100-1.fc44.apex1.x86_64.rpm',
                 'gnome-control-center-50.4-1.fc44.apex1.x86_64.rpm',
                 'gnome-control-center-filesystem-50.4-1.fc44.apex1.noarch.rpm']
        rpms = {name: sha256(rpm_root / 'packages' / name) for name in names}
        if any(checksum != rpm_report['artifacts']['packages/' + name] for name, checksum in rpms.items()):
            raise Blocked('Built RPM checksum mismatch')
        connection = ssh_args(runtime)
        run_id = uuid.uuid4().hex
        export = runtime / 'exports' / run_id
        export.mkdir(mode=0o700)
        source = export_source(export / 'source.tar')
        atomic_json(export / 'source-manifest.json', source)
        atomic_json(export / 'target-image.json', frozen)
        atomic_json(export / 'fingerprint-request.json', {'rpm_build': args.rpm_build, 'gtk_test': args.gtk_test,
                    'gtk_report_sha256': sha256(gtk_dir / 'output/results.json'), 'rpms': rpms})
        remote = '/var/tmp/apex-' + run_id
        subprocess.run(connection + [f'mkdir -m 700 {remote} && mkdir {remote}/inputs'], check=True)
        scp = ['scp', '-i', str(runtime / 'builder_ed25519'), '-P', connection[4], '-o', 'IdentitiesOnly=yes',
               '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', f'UserKnownHostsFile={runtime}/known_hosts']
        subprocess.run(scp + [str(export / name) for name in ('source.tar', 'target-image.json', 'fingerprint-request.json')]
                       + [f'builder@127.0.0.1:{remote}/'], check=True)
        subprocess.run(scp + [str(rpm_root / 'packages' / name) for name in names]
                       + [f'builder@127.0.0.1:{remote}/inputs/'], check=True)
        payload = f'/var/tmp/apex-{args.parent_build}/output/apex-fedora.oci.tar'
        command = (f'cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock '
                   f'bash -c "bash guest/import-payload.sh {payload} target-image.json && python3 guest/fingerprint-image.py"')
        print(export, flush=True)
        with (export / 'build.log').open('wb') as log:
            result = subprocess.run(connection + [command], stdout=log, stderr=subprocess.STDOUT)
        subprocess.run(connection + [f'sudo chown -R builder:builder {remote}/output'], check=True)
        transfer = subprocess.run(scp + ['-r', f'builder@127.0.0.1:{remote}/output', str(export)], check=False)
        atomic_json(export / 'result.json', {'status': 'PASS' if result.returncode == transfer.returncode == 0 else 'FAIL',
                    'kind': 'image', 'profile': 'fedora', 'parent_build': args.parent_build, 'remote': remote,
                    'source_sha256': source['archive_sha256'], 'rpm_build': args.rpm_build, 'gtk_test': args.gtk_test})
        if result.returncode or transfer.returncode:
            raise Blocked(f'Image integration failed; retained evidence: {export}')
        verified = verify(export / 'output', runtime / 'trust/development.pub')
        atomic_json(export / 'verified.json', verified)
        print(json.dumps(verified, indent=2))


if __name__ == '__main__':
    main()

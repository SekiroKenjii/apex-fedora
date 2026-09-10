#!/usr/bin/env python3
"""Build a fresh QCOW2 from the signed A fixture through the normal disk builder."""
import argparse
import fcntl
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
from apexlib.common import Blocked, atomic_json, regular_file, run, sha256, state_dir
from apexlib.pipeline import export_source
from apexlib.testaccess import create
from apexlib.vm import ssh_args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('fixture', type=Path)
    args = parser.parse_args()
    r = state_dir()
    report = json.loads(regular_file(args.fixture / 'output/results.json', within=r).read_text())
    fixture_id = report['id']
    if report['status'] != 'PASS' or not re.fullmatch('[a-f0-9]{32}', fixture_id):
        raise Blocked('A completed signed recovery fixture is required')
    image = report['images']['a']
    if not all(re.fullmatch('sha256:[a-f0-9]{64}', image[k]) for k in ('digest', 'config')):
        raise Blocked('Invalid fixture image digests')
    if sha256(regular_file(args.fixture / 'output/manifest-a.json', within=r)) != image['digest'].removeprefix('sha256:'):
        raise Blocked('Fixture manifest changed')
    with (r / 'build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        connection = ssh_args(r)
        run_id = uuid.uuid4().hex
        destination = r / 'exports' / run_id
        destination.mkdir(mode=0o700)
        manifest = export_source(destination / 'source.tar')
        atomic_json(destination / 'source-manifest.json', manifest)
        target = {'digest': image['digest'], 'image_id': image['config'], 'profile': 'fedora',
                  'fixture': fixture_id, 'ready_to_install': False}
        atomic_json(destination / 'target-image.json', target)
        blueprint = create(destination)
        remote = f'/var/tmp/apex-{run_id}'
        scp = ['scp', '-i', str(r / 'builder_ed25519'), '-P', connection[4],
               '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', f'UserKnownHostsFile={r}/known_hosts']
        run(connection + [f'mkdir -m 700 {remote}'])
        run(scp + [destination / 'source.tar', destination / 'target-image.json', f'builder@127.0.0.1:{remote}/'])
        run(scp + [blueprint, f'builder@127.0.0.1:{remote}/test-blueprint.toml'])
        tag = 'localhost/apex-payload:' + image['digest'].removeprefix('sha256:')
        source_tag = f'localhost/apex-recovery-{fixture_id}:a'
        # disk-artifact.sh checks both the manifest and config IDs before building.
        commands = (f'test "$(cat /etc/apex-builder)" = apex-isolated-builder-v1 && '
                    f'podman tag {source_tag} {tag} && '
                    f'mkdir -p output && skopeo inspect --raw containers-storage:{tag} > output/payload-manifest.json && '
                    f'bash guest/disk-artifact.sh qcow2 {image["config"]} && '
                    'python3 guest/sign-artifacts.py output target-image.json')
        print(destination, flush=True)
        with (destination / 'build.log').open('wb') as log:
            process = subprocess.run(connection + [f'cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock bash -c {shlex.quote(commands)}'], stdout=log, stderr=subprocess.STDOUT)
        run(connection + [f'sudo chown -R builder:builder {remote}/output'])
        transfer = subprocess.run(scp + ['-r', f'builder@127.0.0.1:{remote}/output', str(destination)])
        atomic_json(destination / 'result.json', {'status': 'PASS' if not process.returncode and not transfer.returncode else 'FAIL',
                    'kind': 'qcow2', 'profile': 'fedora', 'parent_fixture': fixture_id, 'digest': image['digest'],
                    'remote': remote, 'test_access': True, 'source_sha256': manifest['archive_sha256'],
                    'scope': 'Fresh installed recovery fixture; boot is NOT TESTED'})
        if process.returncode or transfer.returncode:
            raise Blocked('Recovery disk build failed; logs retained at ' + str(destination))


if __name__ == '__main__':
    main()

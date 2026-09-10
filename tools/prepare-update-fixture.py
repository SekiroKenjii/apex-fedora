#!/usr/bin/env python3
"""Export only public sources and signed payloads for an offline A/B VM test."""
import argparse
import fcntl
import json
import re
import shlex
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
from apexlib.common import Blocked, atomic_json, regular_file, run, sha256, state_dir
from apexlib.pipeline import export_source
from apexlib.vm import ssh_args


def prepare(directory, build_id):
    if not re.fullmatch('[a-f0-9]{32}', build_id):
        raise Blocked('Use a completed image build ID')
    previous = directory / 'exports' / build_id
    result = json.loads(regular_file(previous / 'result.json', within=directory).read_text())
    if result.get('status') != 'PASS' or result.get('kind') != 'image':
        raise Blocked('The parent image build is incomplete')
    frozen = json.loads(regular_file(previous / 'output/image.json', within=directory).read_text())
    if frozen['profile'] != 'fedora' or frozen['digest'] != 'sha256:' + sha256(previous / 'output/manifest.json'):
        raise Blocked('Use the frozen Fedora control image')
    with (directory / 'build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        connection = ssh_args(directory)
        run_id = uuid.uuid4().hex
        export = directory / 'update-fixtures' / run_id
        export.mkdir(parents=True, mode=0o700)
        atomic_json(export / 'source-manifest.json', export_source(export / 'source.tar'))
        atomic_json(export / 'target-image.json', frozen)
        remote = f'/var/tmp/apex-update-{run_id}'
        run(connection + [f'mkdir -m 700 {remote}'])
        scp = ['scp', '-i', str(directory / 'builder_ed25519'), '-P', connection[4],
               '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
               '-o', f'UserKnownHostsFile={directory}/known_hosts']
        run(scp + [export / 'source.tar', export / 'target-image.json', f'builder@127.0.0.1:{remote}/'])
        commands = (f'bash guest/import-payload.sh /var/tmp/apex-{build_id}/output/apex-fedora.oci.tar target-image.json && '
                    'python3 guest/update-fixture.py')
        command = f'cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock bash -c {shlex.quote(commands)}'
        print(export, flush=True)
        with (export / 'build.log').open('wb') as log:
            result = subprocess.run(connection + [command], stdout=log, stderr=subprocess.STDOUT)
        run(connection + [f'sudo chown -R builder:builder {remote}/output'])
        transfer = subprocess.run(scp + ['-r', f'builder@127.0.0.1:{remote}/output', str(export)])
        atomic_json(export / 'execution.json', {'returncode': result.returncode, 'transfer_returncode': transfer.returncode})
        if result.returncode or transfer.returncode:
            raise Blocked(f'Fixture build failed; retained {export}')
        report = json.loads((export / 'output/results.json').read_text())
        if (report.get('status') != 'PASS' or sha256(export / 'output/payloads.tar') != report['archive_sha256']
                or sha256(export / 'output/trusted.pub') != report['public_key_sha256']):
            raise Blocked('Transferred update fixture identity mismatch')
        return export


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('build_id')
    args = parser.parse_args()
    print(prepare(state_dir(), args.build_id))

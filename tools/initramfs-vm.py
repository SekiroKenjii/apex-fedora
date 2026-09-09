#!/usr/bin/env python3
"""Inspect or inject a reviewed initramfs fault in the running test VM."""
import argparse
import base64
import json
from pathlib import Path
import shlex
import shutil
import sys
import uuid

sys.dont_write_bytecode = True
from apexlib.common import ROOT, Blocked, atomic_json, regular_file, sha256, state_dir
from apexlib.guesttest import Guest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'inject'])
    parser.add_argument('fixture', type=Path)
    parser.add_argument('access', type=Path)
    parser.add_argument('--inspection', type=Path)
    args = parser.parse_args()
    runtime = state_dir()
    fixture = json.loads(regular_file(args.fixture / 'output/results.json', within=runtime).read_text())
    if fixture['status'] != 'PASS':
        raise Blocked('A completed signed A/B fixture is required')
    credentials = regular_file(args.access / 'credentials.json', within=runtime)
    guest = Guest(runtime, json.loads(credentials.read_text())['user'], args.access / 'id_ed25519', credentials)
    run_id = uuid.uuid4().hex
    destination = guest.artifacts_dir / ('initramfs-' + args.action + '-' + run_id)
    destination.mkdir(mode=0o700)
    source = ROOT / 'guest/initramfs-fixture.py'
    for path in (source, Path(__file__).resolve()):
        shutil.copyfile(path, destination / path.name)
    report = {'status': 'FAIL', 'action': args.action, 'vm': guest.vm_info,
              'fixture': fixture['id'], 'images': fixture['images'], 'source_sha256': sha256(source)}
    try:
        preimage = None
        if args.action == 'inject':
            if args.inspection is None:
                raise Blocked('Review an inspection result before injecting')
            prior = json.loads(regular_file(args.inspection, within=guest.artifacts_dir).read_text())
            if (prior['status'] != 'PASS' or prior['action'] != 'inspect'
                    or prior['vm'] != guest.vm_info or prior['images'] != fixture['images']
                    or prior['source_sha256'] != report['source_sha256']):
                raise Blocked('Inspection does not match this VM, fixture or source')
            preimage = prior['guest']['sha256']
            report['inspection'] = str(args.inspection)
        script = ('import base64,hashlib; s=base64.b64decode(' + repr(base64.b64encode(source.read_bytes()).decode())
                  + '); assert hashlib.sha256(s).hexdigest()==' + repr(report['source_sha256'])
                  + ';exec(compile(s,"initramfs-fixture.py","exec"))')
        arguments = [args.action, fixture['images']['a']['digest'], fixture['images']['b']['digest']]
        if preimage:
            arguments += ['--run-id', run_id, '--plan-sha256', preimage]
        command = 'unshare --mount --propagation slave python3 -c ' + shlex.quote(script) + ' ' + shlex.join(arguments)
        p = guest.run('sudo -S -p "" ' + command,
                      input=json.loads(credentials.read_text())['password'] + '\n', check=False, timeout=120)
        report['execution'] = {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
        if p.returncode:
            raise Blocked('Guest fixture failed; retain ' + str(destination))
        report['guest'] = json.loads(p.stdout)
        report['status'] = 'PASS'
    finally:
        atomic_json(destination / 'result.json', report)
        print(destination)


if __name__ == '__main__':
    main()

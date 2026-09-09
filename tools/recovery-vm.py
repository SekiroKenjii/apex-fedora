#!/usr/bin/env python3
"""Inspect or instrument one running disposable recovery VM over private SSH."""
import argparse
import base64
import json
from pathlib import Path
import re
import shlex
import shutil
import sys
import uuid

sys.dont_write_bytecode = True
from apexlib.common import ROOT, Blocked, atomic_json, regular_file, sha256, state_dir
from apexlib.guesttest import Guest, assert_candidate


def validate_fixture(fixture):
    if fixture.get('status') != 'PASS' or not re.fullmatch('[a-f0-9]{32}', fixture.get('id', '')):
        raise Blocked('Use a completed, identified A/B fixture')
    values = [fixture.get('images', {}).get(v, {}).get('digest', '') for v in ('a', 'b')]
    if any(not re.fullmatch('sha256:[a-f0-9]{64}', value) for value in values) or values[0] == values[1]:
        raise Blocked('Two distinct complete OCI digests are required')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'verify-installed', 'native-migration', 'repair-grub', 'arm-gdm', 'retry-config', 'reboot', 'collect'])
    parser.add_argument('fixture', type=Path)
    parser.add_argument('access', type=Path)
    args = parser.parse_args()
    runtime = state_dir()
    fixture = json.loads(regular_file(args.fixture / 'output/results.json', within=runtime).read_text())
    validate_fixture(fixture)
    credentials = regular_file(args.access / 'credentials.json', within=runtime)
    guest = Guest(runtime, json.loads(credentials.read_text())['user'], args.access / 'id_ed25519', credentials)
    run_id = uuid.uuid4().hex
    destination = guest.artifacts_dir / ('recovery-' + args.action + '-' + run_id)
    destination.mkdir(mode=0o700)
    proof = {'status': 'FAIL', 'scope': 'Recovery fixture only, not frozen candidate acceptance',
             'action': args.action, 'vm': guest.vm_info, 'fixture': fixture['id'], 'commands': []}
    for name in ('guest/recovery-fixture.py', 'guest/installed-recovery-probe.py', 'tools/recovery-vm.py'):
        target = destination / Path(name).name
        shutil.copyfile(ROOT / name, target)
        proof.setdefault('sources', {})[name] = sha256(target)

    def root(command, timeout=60):
        p = guest.run('sudo -S -p "" ' + command,
                      input=json.loads(credentials.read_text())['password'] + '\n', check=False, timeout=timeout)
        proof['commands'].append({'command': command, 'returncode': p.returncode,
                                  'stdout': p.stdout, 'stderr': p.stderr})
        atomic_json(destination / 'result.json', proof)
        if p.returncode:
            raise Blocked('Guest command failed; evidence retained at ' + str(destination))
        return p.stdout

    def inspect():
        data = {}
        for command in ('bootc status --json', 'rpm -q bootupd greenboot bootc',
                        'grub2-editenv - list', 'cat /boot/grub2/grub.cfg',
                        'cat /etc/greenboot/greenboot.conf',
                        'cat /proc/sys/kernel/random/boot_id',
                        'systemctl show gdm greenboot-healthcheck -p ActiveState -p Result',
                        "sh -c 'sha256sum /boot/grub2/grub.cfg /boot/grub2/grubenv /boot/bootupd-state.json /boot/efi/EFI/*/* /boot/loader/entries/*'",
                        "sh -c 'sha256sum /usr/lib/modules/*/vmlinuz /usr/lib/modules/*/initramfs.img /var/home/apex-test/apex-update-sentinel.txt'"):
            data[command] = root(command)
        return data

    try:
        guest.wait_ready(timeout=45)
        if args.action == 'verify-installed':
            preset = fixture.get('greenboot_config_sha256', '')
            if not re.fullmatch('[a-f0-9]{64}', preset):
                raise Blocked('Use a fixture built with a recorded recovery preset')
            source = (ROOT / 'guest/installed-recovery-probe.py').read_bytes()
            script = 'import base64;exec(compile(base64.b64decode(' + repr(base64.b64encode(source).decode()) + '),"installed-recovery-probe.py","exec"))'
            command = 'python3 -c ' + shlex.quote(script) + ' ' + fixture['images']['a']['digest'] + ' ' + preset
            proof['installed'] = json.loads(root(command))
            proof['status'] = 'PASS'
            return
        proof['before'] = inspect()
        a = fixture['images']['a']['digest']
        b = fixture['images']['b']['digest']
        if args.action in {'native-migration', 'repair-grub', 'arm-gdm', 'retry-config'}:
            assert_candidate(json.loads(proof['before']['bootc status --json']), a)
        if args.action == 'native-migration':
            root('bootupctl migrate-static-grub-config')
            proof['production_migration'] = 'BLOCKED: this command does not refresh an existing static configuration'
        elif args.action == 'reboot':
            state = json.loads(proof['before']['bootc status --json'])
            assert_candidate(state, a)
            if not state['status'].get('staged') or state['status']['staged']['image']['imageDigest'] != b:
                raise Blocked('Stage the signed B fixture before the initial fault reboot')
            request = guest.reboot()
            proof['reboot_request_returncode'] = request.returncode
            if request.returncode not in (0, 255):
                raise Blocked('Guest reboot request failed')
            proof['status'] = 'PASS'
            proof['scope'] = 'One guest reboot requested; recovery is NOT TESTED until collection'
            return
        elif args.action in {'repair-grub', 'arm-gdm', 'retry-config'}:
            source = (ROOT / 'guest/recovery-fixture.py').read_bytes()
            script = 'import base64;exec(compile(base64.b64decode(' + repr(base64.b64encode(source).decode()) + '),"recovery-fixture.py","exec"))'
            command = 'unshare --mount --propagation slave python3 -c ' + shlex.quote(script)
            command += ' ' + args.action + ' --expected-digest ' + a + ' --run-id ' + run_id
            if args.action == 'repair-grub':
                import hashlib
                command += ' --preimage ' + hashlib.sha256(proof['before']['cat /boot/grub2/grub.cfg'].encode()).hexdigest()
            elif args.action == 'arm-gdm':
                command += ' --bad-digest ' + b
            proof['change'] = json.loads(root(command))
        elif args.action == 'collect':
            root('journalctl --list-boots --no-pager')
            root('journalctl -u gdm -u greenboot-healthcheck -u greenboot-set-rollback-trigger --no-pager -o json')
            root("sh -c 'find /var/lib/apex-recovery-test -name \"*.json\" -type f -exec cat {} \\;'")
        proof['after'] = inspect()
        proof['status'] = 'PASS'
    except Exception as error:
        proof['error'] = str(error)
        raise
    finally:
        atomic_json(destination / 'result.json', proof)
        print(destination)


if __name__ == '__main__':
    main()

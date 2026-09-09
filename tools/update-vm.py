#!/usr/bin/env python3
"""Run one explicit A/B operation in an already running disposable test VM."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
from apexlib.common import ROOT, Blocked, atomic_json, regular_file, sha256, state_dir
from apexlib.guesttest import Guest, assert_candidate


def require_rejection(case, returncode, stderr, before, after):
    pattern = 'rejected by policy' if case == 'untrusted' else 'signature'
    if returncode == 0 or not re.search(pattern, stderr, re.I) or before != after:
        raise Blocked('Expected policy rejection with unchanged deployments was not observed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['provision', 'switch-a', 'forward', 'rollback',
                                         'wrong-key', 'unsigned', 'untrusted', 'check-a', 'check-b'])
    parser.add_argument('fixture', type=Path)
    parser.add_argument('access', type=Path)
    args = parser.parse_args()
    runtime = state_dir()
    report_path = regular_file(args.fixture / 'output/results.json', within=runtime)
    fixture = json.loads(report_path.read_text())
    fixture_id = fixture['id']
    if not re.fullmatch('[a-f0-9]{32}', fixture_id) or fixture['status'] != 'PASS':
        raise Blocked('Use a completed update fixture')
    credentials = regular_file(args.access / 'credentials.json', within=runtime)
    guest = Guest(runtime, json.loads(credentials.read_text())['user'], args.access / 'id_ed25519', credentials)
    if args.action in {'wrong-key', 'unsigned', 'untrusted'} and any(guest.artifacts_dir.glob('update-*')):
        raise Blocked('Each rejection case needs a fresh VM overlay without earlier update operations')
    destination = guest.artifacts_dir / f'update-{args.action}-{uuid.uuid4().hex}'
    destination.mkdir(mode=0o700)
    proof = {'status': 'FAIL', 'action': args.action, 'fixture': fixture_id,
             'images': fixture['images'], 'vm': guest.vm_info, 'commands': []}
    remote = '/var/lib/apex-update-fixture/' + fixture_id

    def root(command, *, check=True, timeout=900):
        secret = json.loads(credentials.read_text())['password']
        result = guest.run('sudo -S -p "" ' + command, input=secret + '\n', timeout=timeout, check=False)
        proof['commands'].append({'command': command, 'returncode': result.returncode,
                                  'stdout': result.stdout, 'stderr': result.stderr})
        atomic_json(destination / 'result.json', proof)
        if check and result.returncode:
            raise Blocked(f'Guest command failed: {command}; retained {destination}')
        return result

    def python(source):
        encoded = base64.b64encode(source.encode()).decode()
        return root('python3 -c ' + shlex.quote(f'import base64; exec(compile(base64.b64decode({encoded!r}), "fixture-operation", "exec"))'))

    def status():
        return json.loads(root('bootc status --format json').stdout)

    try:
        guest.wait_ready()
        if root('systemd-detect-virt --vm').stdout.strip() not in {'kvm', 'qemu'}:
            raise Blocked('Only an installed QEMU test guest is supported')
        root('test -f /run/ostree-booted')
        proof['before'] = status()
        if args.action == 'provision':
            assert_candidate(proof['before'], fixture['parent']['digest'])
            archive = regular_file(args.fixture / 'output/payloads.tar', within=runtime)
            if sha256(archive) != fixture['archive_sha256']:
                raise Blocked('Payload archive checksum mismatch')
            upload = f'/var/tmp/apex-update-{fixture_id}.tar'
            # SSH is the same validated localhost-only endpoint used by Guest.
            scp = ['scp', '-i', str(args.access / 'id_ed25519'), '-P', '22245',
                   '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                   '-o', f'UserKnownHostsFile={guest.artifacts_dir}/known-hosts']
            guest.check_vm()
            subprocess.run(scp + [str(archive), f'{guest.user}@127.0.0.1:{upload}'], check=True)
            python(f'''import hashlib,json,os,shutil,tarfile
from pathlib import Path
def digest(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
assert digest({upload!r}) == {fixture['archive_sha256']!r}
base = Path('/var/lib/apex-update-fixture')
target = Path({remote!r})
assert not target.exists()
base.mkdir(mode=0o700,exist_ok=True)
assert not base.is_symlink() and base.stat().st_uid == 0
with tarfile.open({upload!r}) as archive:
    assert all(m.name.split('/')[0] == {fixture_id!r} for m in archive)
    archive.extractall(base, filter='data')
metadata = json.loads((target/'fixture.json').read_text())
assert metadata['id'] == {fixture_id!r}
assert metadata['public_key_sha256'] == {fixture['public_key_sha256']!r}
for name, expected in metadata['files'].items():
    path = target/name
    assert path.resolve().is_relative_to(target) and path.is_file() and not path.is_symlink()
    assert digest(path) == expected, name
policy = json.loads((target/'policy.json').read_text())
assert policy['default'] == [{{'type':'reject'}}]
current = Path('/etc/containers/policy.json')
assert json.loads(current.read_text()) == {{'default':[{{'type':'reject'}}],'transports':{{}}}}
shutil.copyfile(current,target/'bootstrap-policy.json')
shutil.copyfile(target/'policy.json',current)
print(json.dumps({{'bootstrap_policy_sha256':digest(target/'bootstrap-policy.json'),
                  'consumer_policy_sha256':digest(current),'files_verified':len(metadata['files'])}}))
''')
            root('restorecon /etc/containers/policy.json')
            result = guest.run('python3 -', input='from pathlib import Path\np=Path.home()/"apex-update-sentinel.txt"\nassert not p.exists()\np.write_text("Apex A/B user data must survive update and rollback.\\n")\n')
            proof['sentinel_creation'] = result.returncode
        else:
            policy_hash = root('sha256sum /etc/containers/policy.json').stdout.split()[0]
            if policy_hash != fixture['files']['policy.json']:
                raise Blocked('The actual consumer policy differs from the fixture')
            if args.action in {'switch-a', 'forward', 'wrong-key', 'unsigned', 'untrusted'}:
                source = {'switch-a': 'a', 'forward': 'b'}.get(args.action, args.action)
                if args.action != 'switch-a':
                    assert_candidate(proof['before'], fixture['images']['a']['digest'])
                command = 'bootc switch --enforce-container-sigpolicy --transport dir ' + remote + '/' + source
                negative = source in {'wrong-key', 'unsigned', 'untrusted'}
                result = root(command, check=not negative)
                proof['after'] = status()
                if negative:
                    require_rejection(source, result.returncode, result.stderr, proof['before'], proof['after'])
                else:
                    staged = proof['after']['status']['staged']['image']['imageDigest']
                    if staged != fixture['images'][source]['digest']:
                        raise Blocked('Staged digest differs from the signed fixture')
            elif args.action == 'rollback':
                assert_candidate(proof['before'], fixture['images']['b']['digest'])
                if proof['before']['status']['rollback']['image']['imageDigest'] != fixture['images']['a']['digest']:
                    raise Blocked('Rollback does not point to A')
                root('bootc rollback')
                proof['after'] = status()
            else:
                version = args.action[-1]
                guest.expected_digest = fixture['images'][version]['digest']
                assert_candidate(proof['before'], guest.expected_digest)
                proof['health'] = guest.critical_health()
                proof['marker'] = json.loads(guest.run('cat /usr/share/apex/recovery-fixture.json').stdout)
                if proof['marker']['fixture'] != fixture_id or proof['marker']['version'] != version:
                    raise Blocked('Booted immutable marker mismatch')
                guest.password_login_and_render(destination)
                encoded = base64.b64encode((ROOT / 'guest/recovery-probe.py').read_bytes()).decode()
                result = root('python3 -c ' + shlex.quote(f'import base64; exec(compile(base64.b64decode({encoded!r}), "recovery-probe", "exec"))'))
                atomic_json(destination / 'recovery.json', json.loads(result.stdout))
        proof['sentinel_sha256'] = guest.run('sha256sum ~/apex-update-sentinel.txt').stdout.split()[0]
        expected = hashlib.sha256(b'Apex A/B user data must survive update and rollback.\n').hexdigest()
        if proof['sentinel_sha256'] != expected:
            raise Blocked('User data changed')
        proof['status'] = 'PASS'
    finally:
        atomic_json(destination / 'result.json', proof)
        print(destination, flush=True)


if __name__ == '__main__':
    main()

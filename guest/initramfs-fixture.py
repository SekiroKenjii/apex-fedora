#!/usr/bin/python3
"""Corrupt a separate B-only initramfs in a disposable installed QEMU guest."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tempfile


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def parse_entry(text, *, allow_fault=False):
    fields = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        key, sep, value = line.partition(' ')
        if not sep or key in fields:
            raise ValueError('Ambiguous BLS fields')
        fields[key] = value
    if set(fields) != {'title', 'version', 'options', 'linux', 'initrd'}:
        raise ValueError('Review this BLS format before injecting a fault')
    for key in ('linux', 'initrd'):
        value = fields[key]
        if allow_fault and key == 'initrd' and re.fullmatch(r'/apex-initramfs-fault/[a-f0-9]{32}/bad\.img', value):
            continue
        if (not value.startswith('/boot/ostree/') or '..' in PurePosixPath(value).parts
                or re.search(r'\s|[$;]', value)):
            raise ValueError('Expected a single literal boot file')
    links = [v.removeprefix('ostree=') for v in fields['options'].split() if v.startswith('ostree=')]
    if len(links) != 1 or not re.fullmatch(r'/ostree/boot\.[01]/[a-z0-9_-]+/[a-f0-9]{64}/[0-9]+', links[0]):
        raise ValueError('Expected one OSTree bootlink')
    fields['bootlink'] = links[0]
    return fields


def modified_entry(text, new_initrd):
    fields = parse_entry(text)
    if not re.fullmatch(r'/apex-initramfs-fault/[a-f0-9]{32}/bad\.img', new_initrd):
        raise ValueError('Invalid isolated fault path')
    old = 'initrd ' + fields['initrd'] + '\n'
    if not text.endswith('\n') or text.count(old) != 1:
        raise ValueError('Unknown initrd line layout')
    return text.replace(old, 'initrd ' + new_initrd + '\n')


def fingerprint(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Expected a regular final file: ' + str(path))
    st = path.stat()
    return {'sha256': checksum(path), 'size': st.st_size, 'inode': st.st_ino,
            'device': st.st_dev, 'links': st.st_nlink, 'mode': st.st_mode,
            'uid': st.st_uid, 'gid': st.st_gid}


def deployment_path(entry):
    obj = entry['ostree']
    return Path('/sysroot/ostree/deploy') / obj['stateroot'] / 'deploy' / f"{obj['checksum']}.{obj['deploySerial']}"


def require_guest():
    if os.geteuid() or run('systemd-detect-virt', '--vm') not in {'kvm', 'qemu'}:
        raise ValueError('Root inside the disposable QEMU guest is required')
    if not Path('/run/ostree-booted').is_file() or run('getenforce') != 'Enforcing':
        raise ValueError('Expected an enforcing installed guest')
    if os.readlink('/proc/self/ns/mnt') == os.readlink('/proc/1/ns/mnt'):
        raise ValueError('Use a private mount namespace')


def rescue_binding(entries):
    if set(entries) != {'a', 'b'}:
        raise ValueError('Both deployment mappings are required')
    safe = entries['a']['fields']['initrd'].startswith('/boot/ostree/')
    return {'status': 'PASS' if safe else 'BLOCKED', 'safe_to_reboot_a': safe,
            'scope': 'bootlink binding only, not recovery or boot acceptance',
            'reason': 'A uses the original initramfs' if safe else
            'Rollback remapped the fault-bearing BLS entry to A; do not reboot',
            'entries': entries}


def inspect_rescue(good, bad):
    require_guest()
    status = json.loads(run('bootc', 'status', '--json'))['status']
    if (status['booted']['image']['imageDigest'] != good or status.get('staged')
            or status['rollback']['image']['imageDigest'] != bad):
        raise ValueError('Expected rescued A and retained B')
    targets = {'a': deployment_path(status['booted']), 'b': deployment_path(status['rollback'])}
    entries = {}
    paths = list(Path('/boot/loader/entries').glob('*.conf'))
    if len(paths) != 2:
        raise ValueError('Expected exactly two BLS entries')
    for path in paths:
        fields = parse_entry(path.read_text(), allow_fault=True)
        destination = Path(fields['bootlink']).resolve(strict=True)
        matches = [v for v, target in targets.items() if destination == target]
        if len(matches) != 1 or matches[0] in entries:
            raise ValueError('Ambiguous deployment binding after recovery')
        marker = json.loads((destination / 'usr/share/apex/recovery-fixture.json').read_text())
        if marker['version'] != matches[0]:
            raise ValueError('Rescue marker mismatch')
        entries[matches[0]] = {'path': str(path.resolve()), 'fields': fields, 'deployment': str(destination)}
    return rescue_binding(entries)


def inspect(good, bad):
    if good == bad or any(not re.fullmatch('sha256:[a-f0-9]{64}', v) for v in (good, bad)):
        raise ValueError('Two distinct fixture digests are required')
    require_guest()
    status = json.loads(run('bootc', 'status', '--json'))
    state = status['status']
    if (state['booted']['image']['imageDigest'] != good or state.get('staged')
            or not state.get('rollback') or state['rollback']['image']['imageDigest'] != bad
            or not state.get('rollbackQueued')):
        raise ValueError('Finalize signed B through its services while A remains booted')
    for unit in ('ostree-finalize-staged', 'greenboot-set-rollback-trigger'):
        if run('systemctl', 'show', unit, '-p', 'ActiveState', '--value') != 'inactive':
            raise ValueError('Finalization services must have completed before injection')
    if run('rpm', '-q', '--qf', '%{NAME}=%{VERSION}\n', 'bootupd', 'greenboot') != 'bootupd=0.2.35\ngreenboot=0.16.4':
        raise ValueError('Review changed boot components')
    env = dict(line.split('=', 1) for line in run('grub2-editenv', '-', 'list').splitlines())
    if env.get('greenboot_next_deployment_id') != bad or env.get('fallback') != '1' or 'boot_counter' in env:
        raise ValueError('Expected the naturally armed first-update GRUB state')
    targets = {'a': deployment_path(state['booted']), 'b': deployment_path(state['rollback'])}
    entries = {}
    protected = {str(p): fingerprint(p) for p in (Path('/boot/grub2/grub.cfg'), Path('/boot/grub2/grubenv'))}
    for file in Path('/boot/efi/EFI').rglob('*'):
        if file.is_file():
            protected[str(file)] = fingerprint(file)
    paths = list(Path('/boot/loader/entries').glob('*.conf'))
    if len(paths) != 2:
        raise ValueError('Expected exactly two BLS entries')
    for path in paths:
        text = path.read_text()
        fields = parse_entry(text)
        destination = Path(fields['bootlink']).resolve(strict=True)
        matches = [version for version, target in targets.items() if destination == target]
        if len(matches) != 1 or matches[0] in entries:
            raise ValueError('BLS entry does not resolve to exactly one expected deployment')
        version = matches[0]
        marker = json.loads((destination / 'usr/share/apex/recovery-fixture.json').read_text())
        if marker['version'] != version:
            raise ValueError('Deployment marker mismatch')
        files = {}
        for key in ('linux', 'initrd'):
            file = (Path('/boot') / fields[key].lstrip('/')).resolve(strict=True)
            if not file.is_relative_to(Path('/boot').resolve()) or not file.samefile(Path(fields[key])):
                raise ValueError('Ambiguous boot path mapping')
            files[key] = str(file)
            protected[str(file)] = fingerprint(file)
        actual = path.resolve(strict=True)
        if not actual.is_relative_to(Path('/boot')) or path.is_symlink():
            raise ValueError('BLS entry escapes the boot filesystem')
        protected[str(actual)] = fingerprint(actual)
        entries[version] = {'path': str(actual), 'text': text, 'fields': fields, 'files': files,
                            'deployment': str(destination), 'marker': marker}
    if set(entries) != {'a', 'b'} or entries['b']['fields']['version'] != '2' or entries['a']['fields']['version'] != '1':
        raise ValueError('B must be the default entry, with A as the previous deployment')
    return {'bootc': status, 'grubenv': env, 'entries': entries, 'protected': protected,
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def plan_hash(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()


def require_isolated_bootlinks(entries):
    a, b = entries['a'], entries['b']
    if (PurePosixPath(a['fields']['bootlink']).parent == PurePosixPath(b['fields']['bootlink']).parent
            or a['files']['initrd'] == b['files']['initrd']):
        raise ValueError('Shared boot identity can retarget the fault onto A after rollback; use a new isolated fixture')


def inject(plan, run_id, expected_hash):
    if not re.fullmatch('[a-f0-9]{32}', run_id) or plan_hash(plan) != expected_hash:
        raise ValueError('Reviewed plan is missing or changed')
    b = plan['entries']['b']
    source = Path(b['files']['initrd'])
    if source.stat().st_size < 4096:
        raise ValueError('Unexpected source initramfs size')
    bad_ref = f'/apex-initramfs-fault/{run_id}/bad.img'
    after = modified_entry(b['text'], bad_ref)
    for name, identity in plan['protected'].items():
        if fingerprint(Path(name)) != identity:
            raise ValueError('A protected input changed')
    require_isolated_bootlinks(plan['entries'])
    proof = Path('/var/lib/apex-initramfs-test') / run_id
    proof.mkdir(parents=True, exist_ok=False, mode=0o700)
    (proof / 'before.json').write_text(json.dumps(plan, indent=2) + '\n')
    target = Path(b['path'])
    (proof / 'bls-before.conf').write_text(b['text'])
    run('mount', '-o', 'remount,rw', '/boot')
    bad_dir = Path('/boot/apex-initramfs-fault') / run_id
    bad_dir.mkdir(parents=True, exist_ok=False)
    with source.open('rb') as stream:
        data = stream.read(4096)
    data = b'APEX_BAD_INITRD\n' + data[len(b'APEX_BAD_INITRD\n'):]
    bad_file = bad_dir / 'bad.img'
    with bad_file.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    run('chcon', '--reference=' + str(source), str(bad_file))
    fd, temporary = tempfile.mkstemp(prefix='.apex-initramfs-', dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, target.stat().st_mode & 0o777)
        run('chcon', '--reference=' + str(target), temporary)
        if fingerprint(target) != plan['protected'][str(target)]:
            raise ValueError('BLS entry changed during preparation')
        os.replace(temporary, target)
        run('sync', '-f', '/boot')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    for name, identity in plan['protected'].items():
        if name != str(target) and fingerprint(Path(name)) != identity:
            raise ValueError('A protected boot input changed')
    result = {'status': 'PASS', 'scope': 'B-only fault injection, not recovery acceptance',
              'plan_sha256': expected_hash, 'directory': str(proof), 'bad_file': str(bad_file),
              'bad_file_identity': fingerprint(bad_file), 'changed_bls': str(target),
              'bls_after': after, 'bls_after_sha256': checksum(target), 'other_boot_inputs_unchanged': True}
    (proof / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    run('sync', '-f', str(proof))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'inject', 'verify-rescue'])
    parser.add_argument('good_digest')
    parser.add_argument('bad_digest')
    parser.add_argument('--run-id')
    parser.add_argument('--plan-sha256')
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == 'verify-rescue':
        print(json.dumps(inspect_rescue(args.good_digest, args.bad_digest)))
        raise SystemExit(0)
    # Guard the host before creating a guest lock or report directory.
    plan = inspect(args.good_digest, args.bad_digest)
    with Path('/run/apex-initramfs-fixture.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'inspect':
            print(json.dumps({'plan': plan, 'sha256': plan_hash(plan)}))
        else:
            print(json.dumps(inject(plan, args.run_id or '', args.plan_sha256 or '')))

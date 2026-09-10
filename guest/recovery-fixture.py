#!/usr/bin/env python3
"""Diagnostic changes for an installed QEMU fixture, never a release migration."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


BROKEN = b'save_env boot_success### END 08_greenboot.cfg ###'
FIXED = b'save_env boot_success\n### END 08_greenboot.cfg ###'


def repaired_config(current, fragment):
    if not fragment.endswith(b'save_env boot_success\n'):
        raise ValueError('The image fragment must already contain the reviewed newline repair')
    if current.count(BROKEN) != 1 or FIXED in current:
        raise ValueError('Refuse an unknown or already repaired installed configuration')
    return current.replace(BROKEN, FIXED)


def run(*args):
    p = subprocess.run(args, text=True, capture_output=True, check=True)
    return p.stdout


def require_guest(expected):
    if os.geteuid() or run('systemd-detect-virt', '--vm').strip() not in {'kvm', 'qemu'}:
        raise ValueError('Root inside a disposable QEMU test guest is required')
    if not Path('/run/ostree-booted').is_file():
        raise ValueError('An installed OSTree fixture is required')
    if os.readlink('/proc/self/ns/mnt') == os.readlink('/proc/1/ns/mnt'):
        raise ValueError('Use a private mount namespace for fixture changes')
    versions = run('rpm', '-q', '--qf', '%{NAME}=%{VERSION}\n', 'bootupd', 'greenboot')
    if versions != 'bootupd=0.2.35\ngreenboot=0.16.4\n':
        raise ValueError('Review changed bootupd/greenboot versions before mutating the fixture')
    status = json.loads(run('bootc', 'status', '--json'))
    if status['status']['booted']['image']['imageDigest'] != expected:
        raise ValueError('Unexpected booted digest')
    if not status['status'].get('rollback') or status['status'].get('staged'):
        raise ValueError('Use the healthy two-deployment fixture without a staged update')
    return status


def digest(data):
    return hashlib.sha256(data).hexdigest()


def repair_grub(expected_sha, report_dir):
    target = Path('/boot/grub2/grub.cfg')
    if target.is_symlink() or not re.fullmatch('[a-f0-9]{64}', expected_sha):
        raise ValueError('An exact regular-file preimage is required')
    before = target.read_bytes()
    if digest(before) != expected_sha:
        raise ValueError('Installed GRUB preimage changed')
    after = repaired_config(before, Path('/usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg').read_bytes())
    backup = report_dir / 'grub.cfg.before'
    with backup.open('xb') as stream:
        stream.write(before)
        stream.flush()
        os.fsync(stream.fileno())
    env_before = Path('/boot/grub2/grubenv').read_bytes()
    # The caller runs us in a private mount namespace. No ESP or firmware update.
    run('mount', '-o', 'remount,rw', '/boot')
    fd, name = tempfile.mkstemp(prefix='.apex-grub-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(after)
            stream.flush()
            os.fsync(stream.fileno())
        run('grub2-script-check', name)
        run('chcon', '--reference=' + str(target), name)
        if target.read_bytes() != before:
            raise ValueError('GRUB changed during validation')
        os.replace(name, target)
        run('sync', '-f', str(target))
    finally:
        if os.path.exists(name):
            os.unlink(name)
    if Path('/boot/grub2/grubenv').read_bytes() != env_before:
        raise ValueError('Unexpected GRUB environment change')
    return {'status': 'PASS', 'scope': 'VM-only exact newline diagnostic repair',
            'production_migration': 'BLOCKED', 'before_sha256': digest(before),
            'after_sha256': digest(after), 'grubenv_unchanged': True}


def fault_payload(bad_digest, destination):
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', bad_digest):
        raise ValueError('Invalid fault digest')
    # This script survives rollback in /var, but faults only the explicitly named B.
    return f'''#!/usr/bin/python3
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path({str(destination)!r})
boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def capture(args):
    p = subprocess.run(args, text=True, capture_output=True)
    return {{'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}}
status = capture(['bootc', 'status', '--json'])
current = json.loads(status['stdout'])['status']['booted']['image']['imageDigest']
phase = sys.argv[1]
record = {{'boot_id': boot_id, 'phase': phase, 'digest': current, 'bootc': status,
          'grubenv': capture(['grub2-editenv', '-', 'list']),
          'gdm': capture(['systemctl', 'show', 'gdm.service', '-p', 'ActiveState', '-p', 'Result']),
          'injected': phase == 'gdm-start' and current == {bad_digest!r}}}
path = root / (boot_id + '-' + phase + '.json')
with path.open('w') as stream:
    json.dump(record, stream)
    stream.flush()
    os.fsync(stream.fileno())
print('APEX_RECOVERY_OBSERVATION ' + json.dumps(record), flush=True)
if record['injected']:
    sys.exit(42)
'''


def arm_gdm(bad_digest, report_dir):
    source = fault_payload(bad_digest, report_dir)
    program = report_dir / 'observe.py'
    program.write_text(source)
    program.chmod(0o700)
    for unit, text in {
        'gdm.service': '[Service]\nRestart=no\nExecStartPre=/usr/bin/python3 ' + str(program) + ' gdm-start\n',
        'greenboot-healthcheck.service': '[Service]\nExecStartPre=/usr/bin/python3 ' + str(program) + ' health-before\nExecStopPost=/usr/bin/python3 ' + str(program) + ' health-after\n',
    }.items():
        directory = Path('/etc/systemd/system') / (unit + '.d')
        directory.mkdir(exist_ok=True)
        with (directory / '90-apex-recovery-test.conf').open('x') as stream:
            stream.write(text)
    run('systemctl', 'daemon-reload')
    return {'status': 'PASS', 'scope': 'Fault armed for next B boot only, not acceptance',
            'bad_digest': bad_digest, 'program_sha256': digest(source.encode()),
            'directory': str(report_dir)}


def retry_config(report_dir):
    path = Path('/etc/greenboot/greenboot.conf')
    before = path.read_bytes()
    old = b'GREENBOOT_MAX_BOOT_ATTEMPTS=2\n'
    if before.count(old) != 1 or path.is_symlink():
        raise ValueError('Expected the original two-retry fixture configuration')
    (report_dir / 'greenboot.conf.before').write_bytes(before)
    after = before.replace(old, b'GREENBOOT_MAX_BOOT_ATTEMPTS=1\n')
    path.write_bytes(after)
    run('sync', '-f', str(path))
    return {'status': 'PASS', 'scope': 'VM configuration variation, not rebuilt image',
            'before_sha256': digest(before), 'after_sha256': digest(after)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['repair-grub', 'arm-gdm', 'retry-config'])
    parser.add_argument('--expected-digest', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--preimage')
    parser.add_argument('--bad-digest')
    args = parser.parse_args()
    require_guest(args.expected_digest)
    if not re.fullmatch('[a-f0-9]{32}', args.run_id):
        raise ValueError('Invalid run identifier')
    os.umask(0o077)
    destination = Path('/var/lib/apex-recovery-test') / args.run_id
    destination.mkdir(parents=True, exist_ok=False)
    if args.action == 'repair-grub':
        result = repair_grub(args.preimage or '', destination)
    elif args.action == 'arm-gdm':
        result = arm_gdm(args.bad_digest or '', destination)
    else:
        result = retry_config(destination)
    (destination / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()

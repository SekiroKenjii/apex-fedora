#!/usr/bin/python3
"""Inspect recovery prerequisites in an installed test VM without injecting faults."""
import hashlib
import json
import os
from pathlib import Path
import subprocess


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return {'argv': args, 'returncode': result.returncode,
                'stdout': result.stdout[:262144], 'stderr': result.stderr[:262144],
                'truncated': len(result.stdout) > 262144 or len(result.stderr) > 262144}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'argv': args, 'returncode': None, 'error': str(exc)}


def prerequisites(status):
    deployments = status.get('status', {})
    reasons = []
    for slot in ('booted', 'rollback'):
        image = (deployments.get(slot) or {}).get('image') or {}
        if not image.get('imageDigest'):
            reasons.append(f'No {slot} image digest')
    if not reasons and deployments['booted']['image']['imageDigest'] == deployments['rollback']['image']['imageDigest']:
        reasons.append('Booted and rollback images are not distinct test deployments')
    return {'status': 'BLOCKED' if reasons else 'NOT TESTED', 'reasons': reasons,
            'note': 'Two deployments alone do not prove trust, health or automatic recovery'}


def main():
    virtual = command(['systemd-detect-virt', '--vm'])
    if (os.geteuid() != 0 or virtual.get('stdout', '').strip() not in {'kvm', 'qemu'}
            or not Path('/run/ostree-booted').exists()):
        raise RuntimeError('Run only as root in an installed QEMU test VM')
    observations = {label: command(args) for label, args in {
        'bootc': ['bootc', 'status', '--format', 'json'],
        'packages': ['rpm', '-q', 'bootc', 'greenboot', 'grub2-common', 'grub2-tools-minimal'],
        'units': ['systemctl', 'cat', 'greenboot-healthcheck.service', 'greenboot-set-rollback-trigger.service'],
        'unit-state': ['systemctl', 'show', 'greenboot-healthcheck.service', 'greenboot-set-rollback-trigger.service',
                       '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result', '-p', 'UnitFileState'],
        'grub-environment': ['grub2-editenv', '-', 'list'],
        'greenboot-journal': ['journalctl', '-b', '-u', 'greenboot-healthcheck.service',
                              '-u', 'greenboot-set-rollback-trigger.service', '--no-pager', '-n', '300'],
        'failed-units': ['systemctl', '--failed', '--no-legend', '--no-pager'],
        'selinux': ['getenforce'],
    }.items()}
    files = {}
    for filename in ('/etc/greenboot/greenboot.conf', '/boot/grub2/grub.cfg',
                     '/usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg',
                     '/usr/lib/greenboot/check/required.d/20-apex-system.sh'):
        try:
            with Path(filename).open('rb') as stream:
                data = stream.read(262145)
            files[filename] = {'text': data[:262144].decode(errors='replace'), 'truncated': len(data) > 262144,
                               'sha256': hashlib.sha256(data).hexdigest() if len(data) <= 262144 else None}
        except OSError as exc:
            files[filename] = {'error': str(exc)}
    bootc = observations['bootc']
    ready = prerequisites(json.loads(bootc['stdout'])) if bootc['returncode'] == 0 else {'status': 'BLOCKED', 'reasons': ['bootc status failed']}
    print(json.dumps({'scope': 'Read-only installed VM recovery prerequisites', 'recovery_acceptance': 'NOT TESTED',
                      'prerequisites': ready, 'commands': observations, 'files': files}, indent=2))


if __name__ == '__main__':
    main()

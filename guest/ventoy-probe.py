#!/usr/bin/python3
"""Read storage mappings and session state in a disposable Ventoy boot."""
import json
import os
from pathlib import Path
import subprocess


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return {'argv': args, 'returncode': result.returncode, 'stdout': result.stdout[:262144],
                'stderr': result.stderr[:262144], 'truncated': len(result.stdout) > 262144 or len(result.stderr) > 262144}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'argv': args, 'error': str(exc)}


def block_topology(root=Path('/sys/class/block')):
    blocks = {}
    for path in sorted(root.iterdir()):
        # Partitions do not expose a slaves directory; retain that distinction.
        slaves = path / 'slaves'
        blocks[path.name] = {'path': str(path.resolve()), 'ro': (path / 'ro').read_text().strip(),
                             'dev': (path / 'dev').read_text().strip(),
                             'slaves': sorted(item.name for item in slaves.iterdir()) if slaves.is_dir() else None}
    return blocks


def main():
    virtual = command(['systemd-detect-virt', '--vm'])
    if os.geteuid() != 0 or virtual.get('stdout', '').strip() not in {'kvm', 'qemu'}:
        raise RuntimeError('Requires root in a disposable QEMU guest')
    commands = {name: command(args) for name, args in {
        'disks': ['lsblk', '--json', '-o', 'NAME,TYPE,MAJ:MIN,SIZE,FSTYPE,LABEL,RO,MOUNTPOINTS,TRAN,SERIAL,PKNAME'],
        'mounts': ['findmnt', '--json', '-o', 'TARGET,SOURCE,FSTYPE,OPTIONS,MAJ:MIN'],
        'dm-table': ['dmsetup', 'table'], 'dm-info': ['dmsetup', 'info', '-c'],
        'sessions': ['loginctl', 'list-sessions', '--no-legend'],
        'failed-units': ['systemctl', '--failed', '--no-pager', '--no-legend'],
        'gdm': ['systemctl', 'show', 'gdm.service', '-p', 'ActiveState', '-p', 'Result'],
        'firmware-entries': ['efibootmgr', '-v'],
        'selinux': ['getenforce'],
    }.items()}
    print(json.dumps({'scope': 'Read-only virtual Ventoy observations; no automatic acceptance',
                      'commands': commands, 'blocks': block_topology(),
                      'files': {path: Path(path).read_text() for path in ('/proc/cmdline', '/proc/swaps', '/etc/os-release')}}, indent=2))


if __name__ == '__main__':
    main()

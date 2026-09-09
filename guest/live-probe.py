#!/usr/bin/python3
"""Read live-VM observations without changing protection or declaring acceptance."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
        return {'argv': args, 'returncode': result.returncode,
                'stdout': result.stdout[:262144], 'stderr': result.stderr[:262144],
                'truncated': len(result.stdout) > 262144 or len(result.stderr) > 262144}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'argv': args, 'returncode': None, 'error': str(exc)}


def require_live_vm(uid, virtual, cmdline):
    if (uid != 0 or virtual.get('returncode') != 0
            or virtual.get('stdout', '').strip() not in {'kvm', 'qemu'}
            or 'root=live:CDLABEL=Apex-Live' not in cmdline.split()):
        raise RuntimeError('Run only as root in an Apex live QEMU test VM')


def text_file(path):
    try:
        with path.open('rb') as stream:
            data = stream.read(262145)
        return {'text': data[:262144].decode(errors='replace'),
                'truncated': len(data) > 262144,
                'sha256': hashlib.sha256(data).hexdigest() if len(data) <= 262144 else None}
    except OSError as exc:
        return {'error': str(exc)}


def block_observations(root=Path('/sys/class/block')):
    devices = {}
    for entry in sorted(root.iterdir()):
        devices[entry.name] = {'sysfs_path': str(entry.resolve()),
                              'attributes': {name: text_file(entry / name)
                                             for name in ('dev', 'ro', 'size', 'partition', 'device/serial')}}
    return devices


def file_metadata(path):
    try:
        info = path.lstat()
        return {'uid': info.st_uid, 'gid': info.st_gid,
                'mode': oct(stat.S_IMODE(info.st_mode)),
                'selinux': os.getxattr(path, 'security.selinux', follow_symlinks=False)
                             .rstrip(b'\0').decode()}
    except (OSError, UnicodeError) as exc:
        return {'error': str(exc)}


def main():
    virtual = command(['systemd-detect-virt', '--vm'])
    cmdline = Path('/proc/cmdline').read_text()
    require_live_vm(os.geteuid(), virtual, cmdline)
    observations = {label: command(args) for label, args in {
        'mounts': ['findmnt', '--json', '--output', 'TARGET,SOURCE,FSTYPE,OPTIONS,MAJ:MIN'],
        'swap': ['swapon', '--show', '--json', '--bytes'],
        'selinux': ['getenforce'],
        'kernel': ['uname', '-r'],
        'critical-units': ['systemctl', 'show', 'gdm.service', 'apex-live-protection.service',
                           'livesys.service', '-p', 'Id', '-p', 'ActiveState', '-p', 'SubState',
                           '-p', 'Result', '-p', 'ExecMainStatus'],
        'masked-units': ['systemctl', 'show', 'udisks2.service', 'swap.target',
                         'bootc-fetch-apply-updates.service', 'greenboot-healthcheck.service',
                         'bootloader-update.service',
                         '-p', 'Id', '-p', 'UnitFileState', '-p', 'ActiveState'],
        'flatpak-helper': ['systemctl', 'show', 'flatpak-system-helper.service',
                           '-p', 'ActiveState', '-p', 'Result', '-p', 'ExecMainStatus'],
        'failed-units': ['systemctl', '--failed', '--no-legend', '--no-pager'],
        'sessions': ['loginctl', 'list-sessions', '--no-legend'],
        'protection-journal': ['journalctl', '-b', '--no-pager', '-n', '300',
                               '-u', 'apex-live-protection.service', '-u', 'livesys.service'],
        'warnings': ['journalctl', '-b', '--no-pager', '-p', 'warning', '-n', '300'],
        'installer-package': ['rpm', '-q', 'anaconda-core'],
    }.items()}
    files = {name: text_file(Path(name)) for name in (
        '/proc/cmdline', '/proc/swaps', '/run/apex-disks-protected',
        '/run/apex-protection-failed', '/usr/libexec/apex/live-disk-guard.sh')}
    print(json.dumps({'scope': 'Read-only Apex live VM observations',
                      'live_acceptance': 'NOT TESTED', 'write_denial_test': 'NOT TESTED',
                      'commands': observations, 'files': files,
                      'executable_metadata': {name: file_metadata(Path(name)) for name in (
                          '/usr/libexec/flatpak-system-helper',
                          '/run/rootfsbase/usr/libexec/flatpak-system-helper')},
                      'block_devices': block_observations()}, indent=2))


if __name__ == '__main__':
    main()

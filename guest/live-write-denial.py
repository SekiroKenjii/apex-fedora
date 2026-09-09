#!/usr/bin/python3
"""Attempt same-byte writes only on Apex's unmounted live-VM disk fixtures."""
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess


def require_live_vm():
    virtual = subprocess.run(['systemd-detect-virt', '--vm'], capture_output=True, text=True)
    if (os.geteuid() != 0 or virtual.returncode or virtual.stdout.strip() not in {'kvm', 'qemu'}
            or 'root=live:CDLABEL=Apex-Live' not in Path('/proc/cmdline').read_text().split()):
        raise RuntimeError('Requires root in an Apex live QEMU fixture, never physical hardware')


def validate_inventory(devices, mounted, swaps):
    whole = [item for item in devices if item['partition'] is None]
    parts = [item for item in devices if item['partition'] is not None]
    if (len(whole) != 2 or len(parts) != 3
            or sorted(item['sectors'] for item in whole) != [4 * 2**21, 48 * 2**21]):
        raise RuntimeError('Expected only the blank 48 GiB and partitioned 4 GiB fixtures')
    other = next(item for item in whole if item['sectors'] == 4 * 2**21)
    if (other['serial'] != 'apex-other-1'
            or {item['partition'] for item in parts} != {1, 2, 3}
            or any(item['parent'] != other['name'] for item in parts)):
        raise RuntimeError('Fixture serial or partition topology differs')
    for item in devices:
        if (not re.fullmatch(r'vd[a-z]+[0-9]*', item['name']) or not item['virtio']
                or item['ro'] != '1' or item['sectors'] < 1
                or item['holders']
                or item['dev'] in mounted or '/dev/' + item['name'] in swaps):
            raise RuntimeError('Fixture is writable, mounted, swapped or not a virtio device')


def inventory():
    devices = []
    for entry in sorted(Path('/sys/class/block').iterdir()):
        if not re.fullmatch(r'vd[a-z]+[0-9]*', entry.name):
            continue
        resolved = entry.resolve(strict=True)
        partition = entry / 'partition'
        serial = entry / 'device/serial'
        major, minor = map(int, (entry / 'dev').read_text().strip().split(':'))
        info = (Path('/dev') / entry.name).lstat()
        if not stat.S_ISBLK(info.st_mode) or info.st_rdev != os.makedev(major, minor):
            raise RuntimeError('Block node identity differs from sysfs')
        devices.append({'name': entry.name, 'dev': f'{major}:{minor}',
                        'rdev': info.st_rdev, 'ro': (entry / 'ro').read_text().strip(),
                        'sectors': int((entry / 'size').read_text()),
                        'serial': serial.read_text().strip() if serial.exists() else None,
                        'partition': int(partition.read_text()) if partition.exists() else None,
                        'parent': resolved.parent.name,
                        'holders': sorted(path.name for path in (entry / 'holders').iterdir()),
                        'virtio': any(re.fullmatch(r'virtio[0-9]+', part) for part in resolved.parts)})
    mounted = {line.split()[2] for line in Path('/proc/self/mountinfo').read_text().splitlines()}
    swaps = {line.split()[0] for line in Path('/proc/swaps').read_text().splitlines()[1:]}
    # A swap alias or mapped device is not accepted; only the live image's zram is allowed.
    if any(not re.fullmatch(r'/dev/zram[0-9]+', name) for name in swaps):
        raise RuntimeError('Unexpected swap device')
    validate_inventory(devices, mounted, swaps)
    return devices


def attempt(device):
    fd = os.open('/dev/' + device['name'], os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if not stat.S_ISBLK(info.st_mode) or info.st_rdev != device['rdev']:
            raise RuntimeError('Opened device changed identity')
        before = os.pread(fd, 512, 0)
        if len(before) != 512:
            raise RuntimeError('Fixture sector read was incomplete')
        result = {'device': device['name'], 'status': 'FAIL',
                  'method': 'pwrite original 512 bytes at offset zero',
                  'before_sha256': hashlib.sha256(before).hexdigest()}
        try:
            result['bytes_written'] = os.pwrite(fd, before, 0)
        except OSError as exc:
            result.update(errno=exc.errno, error=str(exc))
            if exc.errno in {errno.EPERM, errno.EROFS}:
                result['status'] = 'PASS'
            else:
                result['status'] = 'BLOCKED'
        after = os.pread(fd, 512, 0)
        result['after_sha256'] = hashlib.sha256(after).hexdigest()
        if after != before:
            result['status'] = 'FAIL'
        return result
    finally:
        os.close(fd)


def main():
    require_live_vm()
    devices = inventory()
    results = []
    for device in devices:
        if inventory() != devices:
            raise RuntimeError('Fixture state changed during test')
        result = attempt(device)
        results.append(result)
        if result['status'] != 'PASS':
            break
    passed = len(results) == 5 and all(item['status'] == 'PASS' for item in results)
    status = 'PASS' if passed else next(item['status'] for item in results if item['status'] != 'PASS')
    print(json.dumps({'status': status,
                      'scope': 'Five owned live-VM virtio fixture nodes only',
                      'inventory': devices, 'devices': results,
                      'whole_disk_comparison': 'NOT TESTED',
                      'full_protection_acceptance': 'NOT TESTED'}, indent=2))
    if not passed:
        raise RuntimeError('Write denial did not pass; preserve the VM and inspect the report')


if __name__ == '__main__':
    main()

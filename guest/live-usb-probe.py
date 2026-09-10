#!/usr/bin/python3
"""Check only the emulated USB fixture supplied by the owned QEMU hotplug tool."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from apex_live_write import require_live_vm, attempt


def fixture_parent(path):
    for parent in path.parents:
        serial = parent / 'serial'
        if (any(re.fullmatch(r'usb[0-9]+', part) for part in parent.parts)
                and (parent / 'idVendor').is_file() and (parent / 'idProduct').is_file()
                and serial.is_file() and serial.read_text().strip() == 'apex-usb-fixture'):
            return str(parent)
    return None


def inventory():
    nodes = []
    mounts = {line.split()[2] for line in Path('/proc/self/mountinfo').read_text().splitlines()}
    swap = Path('/proc/swaps').read_text().splitlines()[1:]
    if any(not re.fullmatch(r'/dev/zram[0-9]+', line.split()[0]) for line in swap):
        raise RuntimeError('Disk-backed swap is active')
    for path in sorted(Path('/sys/class/block').iterdir()):
        parent = fixture_parent(path.resolve())
        if not parent:
            continue
        major, minor = map(int, (path / 'dev').read_text().split(':'))
        info = (Path('/dev') / path.name).lstat()
        partition = path / 'partition'
        if (not re.fullmatch(r'sd[a-z]+[0-9]*', path.name) or not stat.S_ISBLK(info.st_mode)
                or info.st_rdev != os.makedev(major, minor)
                or (path / 'dev').read_text().strip() in mounts
                or list((path / 'holders').iterdir()) or (path / 'ro').read_text().strip() != '1'):
            raise RuntimeError('USB fixture is writable, mounted, held or has a wrong identity')
        nodes.append({'name': path.name, 'rdev': info.st_rdev, 'usb_parent': parent,
                      'sectors': int((path / 'size').read_text()),
                      'partition': int(partition.read_text()) if partition.is_file() else None})
    whole = [node for node in nodes if node['partition'] is None]
    if (len(nodes) != 4 or len(whole) != 1 or whole[0]['sectors'] != 4 * 2**21
            or {node['partition'] for node in nodes} != {None, 1, 2, 3}
            or len({node['usb_parent'] for node in nodes}) != 1):
        raise RuntimeError('Expected one 4 GiB USB fixture with three partitions')
    return nodes


def main():
    require_live_vm()
    subprocess.run(['udevadm', 'settle', '--timeout=20'], check=True, timeout=25)
    nodes = inventory()
    results = []
    for node in nodes:
        if inventory() != nodes:
            raise RuntimeError('USB fixture changed during test')
        result = attempt(node)
        results.append(result)
        if result['status'] != 'PASS':
            break
    passed = len(results) == 4 and all(item['status'] == 'PASS' for item in results)
    print(json.dumps({'status': 'PASS' if passed else 'FAIL',
                      'scope': 'Emulated QEMU USB fixture after udev settle',
                      'inventory': nodes, 'writes': results,
                      'whole_disk_comparison': 'NOT TESTED',
                      'physical_usb': 'NOT TESTED', 'hotplug_race_window': 'NOT TESTED'}, indent=2))
    if not passed:
        raise RuntimeError('USB fixture write denial did not pass')


if __name__ == '__main__':
    main()

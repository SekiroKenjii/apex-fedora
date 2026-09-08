#!/usr/bin/python3
"""Create disposable, formatted installer disks inside the isolated builder."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import uuid


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    if os.geteuid() != 0 or Path('/etc/apex-builder').read_text().strip() != 'apex-isolated-builder-v1':
        raise RuntimeError('Fixture formatting requires the isolated Fedora builder')
    if run('systemd-detect-virt', '--vm', capture_output=True, text=True).stdout.strip() not in {'kvm', 'qemu'}:
        raise RuntimeError('Fixture formatting requires a VM')
    # Packages and loop devices are confined to this VM.
    run('dnf5', '-y', 'install', 'dosfstools', 'e2fsprogs', 'ntfs-3g', 'ntfsprogs', 'qemu-img', 'util-linux-core')
    work = Path(tempfile.mkdtemp(prefix='apex-installer-fixtures-', dir='/var/tmp'))
    raw = work / 'other.raw'
    run('truncate', '-s', '4G', raw)
    layout = ('label: gpt\n'
              'size=512M,type=U,name="fixture-efi"\n'
              'size=1024M,type=EBD0A0A2-B9E5-4433-87C0-68B6B72699C7,name="fixture-windows"\n'
              'size=2048M,type=L,name="fixture-linux"\n')
    run('sfdisk', raw, input=layout, text=True)
    loop = run('losetup', '--find', '--show', '--partscan', raw, capture_output=True, text=True).stdout.strip()
    mounted = False
    mount = work / 'mnt'
    mount.mkdir()
    records = []
    try:
        backing = Path('/sys/class/block') / Path(loop).name / 'loop/backing_file'
        if not loop.startswith('/dev/loop') or Path(backing.read_text().strip()).resolve() != raw.resolve():
            raise RuntimeError('Loop device does not refer to the newly created fixture file')
        for index in range(1, 4):
            partition = Path(f'{loop}p{index}')
            for _ in range(50):
                if partition.is_block_device():
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('Fixture partition did not appear')
            if index == 1:
                run('mkfs.vfat', '-F', '32', '-n', 'APEX_EFI', partition)
                mount_type = 'vfat'
            elif index == 2:
                run('mkfs.ntfs', '-Q', '-L', 'APEX_WINDOWS', partition)
                mount_type = 'ntfs-3g'
            else:
                run('mkfs.ext4', '-L', 'APEX_LINUX', partition)
                mount_type = 'ext4'
            run('mount', '-t', mount_type, '-o', 'nosuid,nodev,noexec', partition, mount)
            mounted = True
            sentinel = mount / ('EFI/BOOT/apex-sentinel.txt' if index == 1 else 'apex-sentinel.txt')
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text(f'Disposable Apex installer fixture {index}: {uuid.uuid4().hex}\n')
            records.append({'partition': index, 'filesystem': mount_type,
                            'sentinel': str(sentinel.relative_to(mount)), 'sentinel_sha256': digest(sentinel)})
            run('umount', mount)
            mounted = False
    finally:
        if mounted:
            run('umount', mount)
        run('losetup', '--detach', loop)
    output = Path('output')
    output.mkdir(exist_ok=True)
    run('qemu-img', 'convert', '-f', 'raw', '-O', 'qcow2', raw, output / 'other.qcow2')
    run('qemu-img', 'create', '-f', 'qcow2', output / 'target.qcow2', '48G')
    table = json.loads(run('sfdisk', '--json', raw, capture_output=True, text=True).stdout)
    report = {'purpose': 'installer disk preservation tests', 'bootable_existing_systems': False,
              'layout': table, 'partitions': records, 'retained_work': str(work),
              'sha256': {p.name: digest(p) for p in output.glob('*.qcow2')}}
    (output / 'fixtures.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()

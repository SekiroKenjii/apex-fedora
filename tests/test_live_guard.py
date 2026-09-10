"""Shell control-flow tests with file fixtures, never real block devices."""
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def guard(tmp_path):
    source = (ROOT / 'live/rootfs/usr/libexec/apex/live-disk-guard.sh').read_text()
    # Keep production paths fixed. Only this test copy accepts ordinary files.
    assert source.count('[ -b "$device" ]') == 1
    source = source.replace('[ -b "$device" ]', '[ -f "$device" ]')
    for prefix in ('/sys/', '/dev/', '/run/'):
        source = source.replace(prefix, str(tmp_path) + prefix)
    script = tmp_path / 'guard.sh'
    script.write_text(source)
    for path in ('sys/class/block', 'dev', 'run', 'bin'):
        (tmp_path / path).mkdir(parents=True)
    blockdev = tmp_path / 'bin/blockdev'
    blockdev.write_text('''#!/bin/sh
set -eu
printf '%s %s\n' "$1" "$2" >> "$FIXTURE/calls"
[ "$1" = --setro ] || exit 90
[ "$SETRO" != fail ] || exit 1
if [ "$SETRO" = success ]; then
    printf '1\n' > "$FIXTURE/sys/class/block/${2##*/}/ro"
fi
''')
    blockdev.chmod(0o755)
    mount = tmp_path / 'bin/mount'
    mount.write_text('#!/bin/sh\nexit 1\n')
    mount.chmod(0o755)

    class Fixture:
        def device(self, name, state='0\n', *, virtual=False):
            family = 'virtual/block' if virtual else 'pci0000:00/block'
            path = tmp_path / 'sys/devices' / family / name
            path.mkdir(parents=True)
            (tmp_path / 'sys/class/block' / name).symlink_to(path)
            if state is not None:
                (path / 'ro').write_text(state)
            device = tmp_path / 'dev' / name
            device.touch()
            return device

        def run(self, argument='--verify', mode='success'):
            env = dict(os.environ, PATH=f'{tmp_path}/bin:/usr/bin:/bin',
                       FIXTURE=str(tmp_path), SETRO=mode)
            return subprocess.run(['/bin/sh', script, argument], env=env,
                                  capture_output=True, text=True, timeout=5)

        @property
        def passed(self):
            return (tmp_path / 'run/apex-disks-protected').exists()

        @property
        def calls(self):
            path = tmp_path / 'calls'
            return path.read_text().splitlines() if path.exists() else []

    return Fixture()


def test_empty_optical_drive_uses_kernel_read_only_state(guard):
    guard.device('sr1', '1\n')
    assert guard.run().returncode == 0
    assert guard.passed and guard.calls == []


def test_writable_disk_and_partition_are_locked_and_read_back(guard):
    disk = guard.device('vda')
    part = guard.device('vda1')
    assert guard.run().returncode == 0
    assert guard.passed
    assert guard.calls == [f'--setro {disk}', f'--setro {part}']


@pytest.mark.parametrize('mode', ['fail', 'unchanged'])
def test_lock_failure_or_ineffective_ioctl_blocks_boot(guard, mode):
    guard.device('vda')
    assert guard.run(mode=mode).returncode != 0
    assert not guard.passed


@pytest.mark.parametrize('state', [None, '', '2\n', 'yes\n', '1'])
def test_missing_or_malformed_read_only_state_blocks_boot(guard, state):
    guard.device('vda', state)
    assert guard.run().returncode != 0
    assert not guard.passed and guard.calls == []


def test_udev_failure_stays_latched(guard):
    disk = guard.device('vda')
    assert guard.run(str(disk), mode='fail').returncode != 0
    assert guard.run().returncode != 0
    assert not guard.passed and len(guard.calls) == 1


def test_media_change_event_rechecks_read_only_state(guard):
    optical = guard.device('sr1', '0\n')
    assert guard.run(str(optical)).returncode == 0
    assert guard.calls == [f'--setro {optical}']


def test_missing_device_node_blocks_boot(guard):
    guard.device('vda').unlink()
    assert guard.run().returncode != 0
    assert not guard.passed and guard.calls == []


def test_no_devices_cannot_pass(guard):
    assert guard.run().returncode != 0
    assert not guard.passed


def test_live_overlay_remains_writable_but_disk_is_protected(guard):
    guard.device('loop0', virtual=True)
    guard.device('dm-0', virtual=True)
    guard.device('zram0', virtual=True)
    disk = guard.device('vda')
    assert guard.run().returncode == 0
    assert guard.calls == [f'--setro {disk}']


def test_firmware_remount_failure_blocks_desktop(guard, tmp_path):
    guard.device('vda', '1\n')
    (tmp_path / 'sys/firmware/efi/efivars').mkdir(parents=True)
    assert guard.run().returncode != 0
    assert not guard.passed

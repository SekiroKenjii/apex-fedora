"""The live disk guard, run exactly as it ships, against a root the test controls.

The script names `/sys`, `/dev` and `/run` and tests block devices with `-b`. Nothing in it
is rewritten here. A user namespace binds fixture directories over those paths and a real
block node over each fixture device, so the script reads what the test arranged and writes
where the test can see, while `blockdev` and `mount` are shims on the path that record what
they were asked and do nothing to the host.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / "live/rootfs/usr/libexec/apex/live-disk-guard.sh"
BLOCK_NODE = Path("/dev/loop0")
UNSHARE = ["unshare", "--user", "--map-root-user", "--mount"]

BLOCKDEV_SHIM = """#!/bin/sh
set -eu
printf '%s %s\\n' "$1" "$2" >> "$FIXTURE/calls"
[ "$1" = --setro ] || exit 90
[ "$SETRO" != fail ] || exit 1
if [ "$SETRO" = success ]; then
    printf '1\\n' > "/sys/class/block/${2##*/}/ro"
fi
"""
MOUNT_SHIM = "#!/bin/sh\nexit 1\n"


def namespaces_available() -> bool:
    if shutil.which("unshare") is None or not BLOCK_NODE.exists():
        return False
    probe = subprocess.run([*UNSHARE, "true"], capture_output=True)
    return probe.returncode == 0


pytestmark = pytest.mark.skipif(
    not namespaces_available(), reason="NOT TESTED: user namespaces or a block node unavailable"
)


@dataclass
class Fixture:
    root: Path
    nodes: list[str] = field(default_factory=list)

    def device(self, name: str, state: str | None = "0\n", *, virtual: bool = False) -> Path:
        family = "virtual/block" if virtual else "pci0000:00/block"
        real = self.root / "sys/devices" / family / name
        real.mkdir(parents=True)
        (self.root / "sys/class/block" / name).symlink_to(f"/sys/devices/{family}/{name}")
        if state is not None:
            (real / "ro").write_text(state)
        node = self.root / "dev" / name
        node.touch()
        self.nodes.append(name)
        return Path("/dev") / name

    def forget_node(self, name: str) -> None:
        self.nodes.remove(name)

    def run(
        self, argument: str = "--verify", mode: str = "success"
    ) -> subprocess.CompletedProcess[str]:
        binds = " && ".join(
            f"mount --bind {BLOCK_NODE} {self.root}/dev/{name}" for name in self.nodes
        )
        script = " && ".join(
            part
            for part in (
                binds,
                f"mount --bind {self.root}/sys /sys",
                f"mount --rbind {self.root}/dev /dev",
                f"mount --bind {self.root}/run /run",
                f"export PATH={self.root}/bin:/usr/bin:/bin",
                f"exec /bin/sh {SCRIPT} {argument}",
            )
            if part
        )
        env = dict(os.environ, FIXTURE=str(self.root), SETRO=mode)
        return subprocess.run(
            [*UNSHARE, "sh", "-c", script], env=env, capture_output=True, text=True, timeout=20
        )

    @property
    def passed(self) -> bool:
        return (self.root / "run/apex-disks-protected").exists()

    @property
    def calls(self) -> list[str]:
        path = self.root / "calls"
        return path.read_text().splitlines() if path.exists() else []


@pytest.fixture
def guard(tmp_path: Path) -> Fixture:
    for path in ("sys/class/block", "dev", "run", "bin"):
        (tmp_path / path).mkdir(parents=True)
    (tmp_path / "bin/blockdev").write_text(BLOCKDEV_SHIM)
    (tmp_path / "bin/blockdev").chmod(0o755)
    (tmp_path / "bin/mount").write_text(MOUNT_SHIM)
    (tmp_path / "bin/mount").chmod(0o755)
    return Fixture(tmp_path)


def test_the_script_under_test_is_the_one_that_ships() -> None:
    text = SCRIPT.read_text()

    assert '[ -b "$device" ]' in text
    assert "/sys/class/block" in text


def test_empty_optical_drive_uses_kernel_read_only_state(guard: Fixture) -> None:
    guard.device("sr1", "1\n")

    assert guard.run().returncode == 0
    assert guard.passed and guard.calls == []


def test_writable_disk_and_partition_are_locked_and_read_back(guard: Fixture) -> None:
    disk = guard.device("vda")
    part = guard.device("vda1")

    assert guard.run().returncode == 0
    assert guard.passed
    assert guard.calls == [f"--setro {disk}", f"--setro {part}"]


@pytest.mark.parametrize("mode", ["fail", "unchanged"])
def test_lock_failure_or_ineffective_ioctl_blocks_boot(guard: Fixture, mode: str) -> None:
    guard.device("vda")

    assert guard.run(mode=mode).returncode != 0
    assert not guard.passed


@pytest.mark.parametrize("state", [None, "", "2\n", "yes\n", "1"])
def test_missing_or_malformed_read_only_state_blocks_boot(
    guard: Fixture, state: str | None
) -> None:
    guard.device("vda", state)

    assert guard.run().returncode != 0
    assert not guard.passed and guard.calls == []


def test_udev_failure_stays_latched(guard: Fixture) -> None:
    disk = guard.device("vda")

    assert guard.run(str(disk), mode="fail").returncode != 0
    assert guard.run().returncode != 0
    assert not guard.passed and len(guard.calls) == 1


def test_media_change_event_rechecks_read_only_state(guard: Fixture) -> None:
    optical = guard.device("sr1", "0\n")

    assert guard.run(str(optical)).returncode == 0
    assert guard.calls == [f"--setro {optical}"]


def test_missing_device_node_blocks_boot(guard: Fixture) -> None:
    guard.device("vda")
    guard.forget_node("vda")

    assert guard.run().returncode != 0
    assert not guard.passed and guard.calls == []


def test_no_devices_cannot_pass(guard: Fixture) -> None:
    assert guard.run().returncode != 0
    assert not guard.passed


def test_live_overlay_remains_writable_but_disk_is_protected(guard: Fixture) -> None:
    guard.device("loop0", virtual=True)
    guard.device("dm-0", virtual=True)
    guard.device("zram0", virtual=True)
    disk = guard.device("vda")

    assert guard.run().returncode == 0
    assert guard.calls == [f"--setro {disk}"]


def test_firmware_remount_failure_blocks_desktop(guard: Fixture) -> None:
    guard.device("vda", "1\n")
    (guard.root / "sys/firmware/efi/efivars").mkdir(parents=True)

    assert guard.run().returncode != 0
    assert not guard.passed

"""A snapshot reads the tree once and answers in constant time afterwards.

The threshold the plan names: two hundred devices, and no more than a fixed number of port
calls per device to take the snapshot, then none at all to look one up. The fake counts
every call, so the bound is a number the test states rather than a feeling about speed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import fake_files
from apex.agent import blockdevices
from apex.kernel import errors, quantities, refusals, safepaths
from apex.ports import files

ROOT = safepaths.SafePath(Path("/sys/class/block"))
DEVICES = safepaths.SafePath(Path("/sys/devices/pci0000:00"))
PRIVATE = quantities.FileMode(0o644)
CALLS_PER_DEVICE = 9
VIRTIO = re.compile(r"virtio[0-9]+")
PORT_METHODS = frozenset(
    name
    for name in dir(files.FileSystemPort)
    if not name.startswith("_") and callable(getattr(files.FileSystemPort, name))
)


class Counting(fake_files.MemoryFiles):
    """Counts calls made through the port, not the calls the fake makes on itself."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0
        self.depth = 0

    def __getattribute__(self, name: str) -> Any:
        attribute = super().__getattribute__(name)
        if name not in PORT_METHODS:
            return attribute

        def counted(*arguments: Any, **keywords: Any) -> Any:
            if self.depth == 0:
                self.count += 1
            self.depth += 1
            try:
                return attribute(*arguments, **keywords)
            finally:
                self.depth -= 1

        return counted


def disk(tree: fake_files.MemoryFiles, name: str, *, index: int, serial: str | None) -> None:
    home = DEVICES / f"0000:00:{index:02x}.0" / f"virtio{index}" / "block" / name
    tree.write_atomic(home / "dev", f"253:{index * 16}\n".encode(), mode=PRIVATE)
    tree.write_atomic(home / "ro", b"1\n", mode=PRIVATE)
    tree.write_atomic(home / "size", b"8388608\n", mode=PRIVATE)
    if serial is not None:
        tree.write_atomic(home / "serial", f"{serial}\n".encode(), mode=PRIVATE)
    tree.make_directory(home / "holders", mode=PRIVATE)
    tree.make_directory(home / "slaves", mode=PRIVATE)
    tree.symlink(ROOT / name, target=home)


def partition(tree: fake_files.MemoryFiles, disk_name: str, number: int, *, index: int) -> None:
    home = DEVICES / f"0000:00:{index:02x}.0" / f"virtio{index}" / "block" / disk_name
    part = home / f"{disk_name}{number}"
    tree.write_atomic(part / "dev", f"253:{index * 16 + number}\n".encode(), mode=PRIVATE)
    tree.write_atomic(part / "ro", b"1\n", mode=PRIVATE)
    tree.write_atomic(part / "size", b"2048\n", mode=PRIVATE)
    tree.write_atomic(part / "partition", f"{number}\n".encode(), mode=PRIVATE)
    tree.make_directory(part / "holders", mode=PRIVATE)
    tree.symlink(ROOT / f"{disk_name}{number}", target=part)


def fixture(count: int) -> Counting:
    tree = Counting()
    tree.make_directory(ROOT, mode=PRIVATE)
    for index in range(count):
        disk(tree, f"vd{index:03d}", index=index, serial=f"apex-{index}")
    return tree


def test_two_hundred_devices_cost_a_bounded_number_of_calls_and_lookups_cost_none() -> None:
    tree = fixture(200)
    tree.count = 0

    snapshot = blockdevices.Snapshot.take(tree, root=ROOT)
    taken = tree.count

    assert len(snapshot.devices) == 200
    assert taken <= 1 + CALLS_PER_DEVICE * 200
    for index in range(200):
        found = snapshot.by_number(files.DeviceNumber(253, index * 16))
        assert found is not None and found.name == f"vd{index:03d}"
        assert snapshot.by_name(f"vd{index:03d}") is found
    assert tree.count == taken


def test_a_partition_knows_its_disk_and_has_no_slaves() -> None:
    tree = fixture(1)
    partition(tree, "vd000", 1, index=0)

    snapshot = blockdevices.Snapshot.take(tree, root=ROOT)
    part = snapshot.by_name("vd0001")

    assert part is not None
    assert part.partition == 1
    assert part.parent == "vd000"
    assert part.slaves is None
    assert part.serial is None
    whole = snapshot.by_name("vd000")
    assert whole is not None and whole.partition is None and whole.slaves == ()
    assert whole.on_bus(VIRTIO) and part.on_bus(VIRTIO)


def test_the_generation_changes_when_any_attribute_changes() -> None:
    tree = fixture(3)
    before = blockdevices.Snapshot.take(tree, root=ROOT)
    same = blockdevices.Snapshot.take(tree, root=ROOT)
    home = DEVICES / "0000:00:01.0" / "virtio1" / "block" / "vd001"
    tree.write_atomic(home / "ro", b"0\n", mode=PRIVATE)

    after = blockdevices.Snapshot.take(tree, root=ROOT)

    assert before.same_as(same)
    assert not before.same_as(after)


def test_a_pattern_selects_by_name() -> None:
    tree = fixture(2)
    tree.write_atomic(DEVICES / "zram" / "zram0" / "dev", b"252:0\n", mode=PRIVATE)
    tree.write_atomic(DEVICES / "zram" / "zram0" / "ro", b"0\n", mode=PRIVATE)
    tree.write_atomic(DEVICES / "zram" / "zram0" / "size", b"16\n", mode=PRIVATE)
    tree.symlink(ROOT / "zram0", target=DEVICES / "zram" / "zram0")

    everything = blockdevices.Snapshot.take(tree, root=ROOT)
    only_virtio = blockdevices.Snapshot.take(tree, root=ROOT, matching=re.compile(r"vd[0-9]+"))

    assert [device.name for device in everything.devices] == ["vd000", "vd001", "zram0"]
    assert [device.name for device in only_virtio.devices] == ["vd000", "vd001"]


def test_a_device_without_a_number_is_refused() -> None:
    tree = fixture(1)
    tree.remove(DEVICES / "0000:00:00.0" / "virtio0" / "block" / "vd000" / "dev")

    with pytest.raises(errors.Refusal) as caught:
        blockdevices.Snapshot.take(tree, root=ROOT)

    assert caught.value.reason is refusals.RefusalReason.SYSFS_ATTRIBUTE_MALFORMED


def test_a_size_that_is_not_a_count_is_refused() -> None:
    tree = fixture(1)
    home = DEVICES / "0000:00:00.0" / "virtio0" / "block" / "vd000"
    tree.write_atomic(home / "size", b"large\n", mode=PRIVATE)

    with pytest.raises(errors.Refusal) as caught:
        blockdevices.Snapshot.take(tree, root=ROOT)

    assert caught.value.reason is refusals.RefusalReason.SYSFS_ATTRIBUTE_MALFORMED


def test_the_document_carries_the_sysfs_spelling() -> None:
    tree = fixture(1)

    document = blockdevices.Snapshot.take(tree, root=ROOT).document()

    assert document["vd000"] == {
        "name": "vd000",
        "sysfs_path": "/sys/devices/pci0000:00/0000:00:00.0/virtio0/block/vd000",
        "dev": "253:0",
        "ro": "1",
        "sectors": 8388608,
        "partition": None,
        "serial": "apex-0",
        "holders": [],
        "slaves": [],
    }

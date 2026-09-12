"""The fault units judge a fixture, a write and a run the way the older scripts did.

The older scripts open devices with the standard library, so they are run with those calls
answered rather than through ports. Three judgements are compared: whether an inventory is
accepted, what status a write outcome earns, and which devices a run attempts before it
stops. The inputs to both sides come from one spec, so a mutation reaches both.
"""

from __future__ import annotations

import errno
import importlib.util
import stat
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from livefixture_trees import DeviceSpec, guest, usb_fixture, virtio_fixture

from apex.adapters.fakes import fake_blockdevices
from apex.agent import guestguard, livefixtures
from apex.agent.units import live_write_denial_unit
from apex.kernel import errors

REPOSITORY = Path(__file__).resolve().parents[2]


def older(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPOSITORY / "guest" / name
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def older_devices(specs: list[DeviceSpec]) -> list[dict[str, Any]]:
    """The older inventory dict for each spec, as `live-write-denial.py` would build it."""
    return [
        {
            "name": spec.name,
            "dev": f"{spec.major}:{spec.minor}",
            "rdev": spec.major * 256 + spec.minor,
            "ro": spec.ro,
            "sectors": spec.sectors,
            "serial": spec.serial,
            "partition": spec.partition,
            "parent": spec.parent or "block",
            "holders": list(spec.holders),
            "virtio": spec.bus.startswith("virtio"),
        }
        for spec in specs
    ]


def older_accepts(
    module: types.ModuleType, specs: list[DeviceSpec], mounted: set[str], swaps: set[str]
) -> bool:
    try:
        module.validate_inventory(older_devices(specs), mounted, swaps)
    except RuntimeError:
        return False
    return True


def newer_accepts(specs: list[DeviceSpec], *, mountinfo: str, swaps: str) -> bool:
    fixture = guest(specs, mountinfo=mountinfo, swaps=swaps)
    try:
        inventory = livefixtures.Inventory.take(
            fixture.ports(), matching=livefixtures.VIRTIO_NAME
        )
        livefixtures.require_live_fixture(inventory)
    except errors.Refusal:
        return False
    return True


OTHER = 4 * 2**21
SENTINEL = "apex-other-1"


def first_replaced(specs: list[DeviceSpec], device: DeviceSpec) -> list[DeviceSpec]:
    return [device, *specs[1:]]


MUTATIONS = {
    "as-built": lambda specs: specs,
    "nvme-name": lambda specs: first_replaced(specs, DeviceSpec("nvme0n1", OTHER, serial=SENTINEL)),
    "one-sector": lambda specs: first_replaced(specs, DeviceSpec("vda", 1, serial=SENTINEL)),
    "wrong-serial": lambda specs: first_replaced(
        specs, DeviceSpec("vda", OTHER, serial="unrelated")
    ),
    "writable": lambda specs: first_replaced(
        specs, DeviceSpec("vda", OTHER, serial=SENTINEL, ro="0")
    ),
    "held": lambda specs: first_replaced(
        specs, DeviceSpec("vda", OTHER, serial=SENTINEL, holders=("dm-0",))
    ),
    "other-bus": lambda specs: first_replaced(
        specs, DeviceSpec("vda", OTHER, serial=SENTINEL, bus="nvme0")
    ),
    "missing-partition": lambda specs: specs[:-2] + specs[-1:],
    "extra-disk": lambda specs: [*specs, DeviceSpec("vdc", OTHER, bus="virtio3", minor=32)],
    "wrong-parent": lambda specs: [
        *specs[:3],
        DeviceSpec("vda3", 100, partition=3, parent="vdb", bus="virtio2", minor=3),
        *specs[4:],
    ],
}


@pytest.mark.parametrize("mutation", sorted(MUTATIONS))
def test_both_sides_accept_or_refuse_the_same_inventories(
    mutation: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)
    specs = MUTATIONS[mutation](virtio_fixture())
    module = older("live-write-denial.py")

    before = older_accepts(module, specs, set(), set())
    after = newer_accepts(
        specs,
        mountinfo="22 1 0:21 / / rw - overlay overlay rw\n",
        swaps="Filename Type Size Used Priority\n",
    )

    assert after == before
    assert before == (mutation == "as-built")


@pytest.mark.parametrize("use", ["mounted", "swap"])
def test_both_sides_refuse_a_fixture_in_use(use: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)
    module = older("live-write-denial.py")
    specs = virtio_fixture()
    mounted = {"253:2"} if use == "mounted" else set()
    swaps = {"/dev/vda2"} if use == "swap" else set()
    mountinfo = "22 1 0:21 / / rw - overlay overlay rw\n" + (
        "30 22 253:2 / /mnt rw - ext4 /dev/vda2 rw\n" if use == "mounted" else ""
    )
    swap_table = "Filename Type Size Used Priority\n" + (
        "/dev/vda2 partition 100 0 -2\n" if use == "swap" else ""
    )

    assert not older_accepts(module, specs, mounted, swaps)
    assert not newer_accepts(specs, mountinfo=mountinfo, swaps=swap_table)


OUTCOMES = [
    (errno.EPERM, False, "PASS"),
    (errno.EROFS, False, "PASS"),
    (errno.EIO, False, "BLOCKED"),
    (errno.ENOSPC, False, "BLOCKED"),
    (None, False, "FAIL"),
    (errno.EPERM, True, "FAIL"),
]


@pytest.mark.parametrize("outcome,changes,expected", OUTCOMES)
def test_both_sides_give_a_write_outcome_the_same_status(
    outcome: int | None, changes: bool, expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = older("live-write-denial.py")
    reads = iter([b"a" * 512, (b"b" if changes else b"a") * 512])
    monkeypatch.setattr(module.os, "open", lambda *_: 19)
    monkeypatch.setattr(
        module.os, "fstat", lambda _: types.SimpleNamespace(st_mode=stat.S_IFBLK, st_rdev=7)
    )
    monkeypatch.setattr(module.os, "pread", lambda *_: next(reads))
    monkeypatch.setattr(module.os, "close", lambda _: None)

    def pwrite(_fd: int, data: bytes, _offset: int) -> int:
        if outcome is not None:
            raise OSError(outcome, "fixture error")
        return len(data)

    monkeypatch.setattr(module.os, "pwrite", pwrite)
    before = module.attempt({"name": "vda", "rdev": 7})

    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)
    fixture = guest(virtio_fixture())
    declared = fixture.blocks.nodes["/dev/vda"]
    fixture.blocks.nodes["/dev/vda"] = fake_blockdevices.FakeNode(
        number=declared.number, content=b"a" * 512, denial=outcome, changes_on_write=changes
    )
    device = livefixtures.Inventory.take(
        fixture.ports(), matching=livefixtures.VIRTIO_NAME
    ).devices[0]
    after = livefixtures.attempt(fixture.ports(), device)

    assert after["status"] == before["status"] == expected
    assert (after["before_sha256"] == after["after_sha256"]) == (
        before["before_sha256"] == before["after_sha256"]
    )


def test_both_sides_attempt_the_same_devices_and_stop_at_the_same_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = older("live-write-denial.py")
    attempted: list[str] = []

    def older_attempt(device: dict[str, Any]) -> dict[str, Any]:
        attempted.append(device["name"])
        return {"status": "PASS" if device["name"] != "vda2" else "FAIL"}

    monkeypatch.setattr(module, "require_live_vm", lambda: None)
    monkeypatch.setattr(module, "inventory", lambda: older_devices(virtio_fixture()))
    monkeypatch.setattr(module, "attempt", older_attempt)
    with pytest.raises(RuntimeError):
        module.main()
    capsys.readouterr()

    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)
    fixture = guest(virtio_fixture())
    declared = fixture.blocks.nodes["/dev/vda2"]
    fixture.blocks.nodes["/dev/vda2"] = fake_blockdevices.FakeNode(
        number=declared.number, content=declared.content, denial=None
    )
    report = live_write_denial_unit.run(fixture.ports(), arguments={})

    assert [item.node.removeprefix("/dev/") for item in fixture.blocks.attempts] == attempted
    assert attempted == ["vda", "vda1", "vda2"]
    assert report["status"] == "FAIL"


def test_both_sides_find_the_usb_fixture_parent_the_same_way(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The older `fixture_parent` walks real directories; the tree is mirrored on disk."""
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)
    write_denial = older("live-write-denial.py")
    monkeypatch.setitem(sys.modules, "apex_live_write", write_denial)
    module = older("live-usb-probe.py")
    for serial, expected in (("apex-usb-fixture", True), ("someone-else", False)):
        fixture = guest(usb_fixture(), usb_serial=serial)
        inventory = livefixtures.Inventory.take(fixture.ports(), matching=livefixtures.USB_NAME)
        device = inventory.devices[0]
        mirrored = tmp_path / serial / device.sysfs_path.lstrip("/")
        mirrored.mkdir(parents=True)
        usb = tmp_path / serial / "sys/devices/pci0000:00/0000:00:14.0/usb1/1-1"
        (usb / "idVendor").write_text("0781\n")
        (usb / "idProduct").write_text("5583\n")
        (usb / "serial").write_text(f"{serial}\n")

        before = module.fixture_parent(mirrored)
        after = livefixtures.usb_parent(fixture.ports(), device)

        assert (before is not None) == (after is not None) == expected
        if before is not None:
            assert before.removeprefix(str(tmp_path / serial)) == after

"""The two write-denial faults write only to the fixtures they expect, and report the kernel."""

from __future__ import annotations

import errno
from pathlib import Path

import pytest
from livefixture_trees import DeviceSpec, guest, home_of, usb_fixture, virtio_fixture

from apex.adapters.fakes import fake_blockdevices, fake_process
from apex.agent import guestguard, livefixtures
from apex.agent.units import live_write_denial_unit, usb_write_denial_unit
from apex.kernel import errors, quantities, refusals, safepaths
from apex.ports import blockdevices
from apex.ports import files as files_port


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)


def refused(action: object) -> refusals.RefusalReason:
    with pytest.raises(errors.Refusal) as caught:
        action()  # type: ignore[operator]
    return caught.value.reason


def accepting(node: str, tree: object, *, changes: bool = False) -> None:
    assert isinstance(tree, fake_blockdevices.FakeBlockDevices)
    declared = tree.nodes[node]
    tree.nodes[node] = fake_blockdevices.FakeNode(
        number=declared.number, content=declared.content, denial=None, changes_on_write=changes
    )


def test_every_virtio_fixture_denied_is_a_pass_in_snapshot_order() -> None:
    fixture = guest(virtio_fixture())

    report = live_write_denial_unit.run(fixture.ports(), arguments={})

    assert report["status"] == "PASS"
    assert [item.node for item in fixture.blocks.attempts] == [
        "/dev/vda", "/dev/vda1", "/dev/vda2", "/dev/vda3", "/dev/vdb",
    ]
    devices = report["devices"]
    assert isinstance(devices, list) and len(devices) == 5
    first = devices[0]
    assert isinstance(first, dict)
    assert first["status"] == "PASS" and first["errno"] == errno.EROFS
    assert first["before_sha256"] == first["after_sha256"]
    assert report["full_protection_acceptance"] == "NOT TESTED"
    assert report["whole_disk_comparison"] == "NOT TESTED"


def test_the_first_accepted_write_fails_the_fault_and_stops_the_rest() -> None:
    fixture = guest(virtio_fixture())
    accepting("/dev/vda1", fixture.blocks)

    report = live_write_denial_unit.run(fixture.ports(), arguments={})

    assert report["status"] == "FAIL"
    assert [item.node for item in fixture.blocks.attempts] == ["/dev/vda", "/dev/vda1"]


def test_another_error_is_blocked_not_passed() -> None:
    fixture = guest(virtio_fixture())
    declared = fixture.blocks.nodes["/dev/vda"]
    fixture.blocks.nodes["/dev/vda"] = fake_blockdevices.FakeNode(
        number=declared.number, content=declared.content, denial=errno.EIO
    )

    report = live_write_denial_unit.run(fixture.ports(), arguments={})

    assert report["status"] == "BLOCKED"
    assert len(fixture.blocks.attempts) == 1


def test_a_denied_write_whose_readback_changed_is_a_failure() -> None:
    fixture = guest(virtio_fixture())
    accepting("/dev/vda", fixture.blocks, changes=True)

    report = live_write_denial_unit.run(fixture.ports(), arguments={})

    assert report["status"] == "FAIL"


@pytest.mark.parametrize(
    "change",
    [
        "writable", "wrong-serial", "extra-disk", "missing-partition", "wrong-parent", "held",
        "other-bus",
    ],
)
def test_a_fixture_that_differs_is_refused_before_any_write(change: str) -> None:
    specs = virtio_fixture()
    if change == "writable":
        specs[4] = DeviceSpec("vdb", 48 * 2**21, bus="virtio2", minor=16, ro="0")
    elif change == "wrong-serial":
        specs[0] = DeviceSpec("vda", 4 * 2**21, serial="unrelated", minor=0)
    elif change == "extra-disk":
        specs.append(DeviceSpec("vdc", 100, bus="virtio3", minor=32))
    elif change == "missing-partition":
        specs.pop(3)
    elif change == "wrong-parent":
        specs[3] = DeviceSpec("vda3", 100, partition=3, parent="vdb", bus="virtio2", minor=3)
    elif change == "held":
        specs[4] = DeviceSpec("vdb", 48 * 2**21, bus="virtio2", minor=16, holders=("dm-0",))
    else:
        specs[4] = DeviceSpec("vdb", 48 * 2**21, bus="nvme0", minor=16)
    fixture = guest(specs)

    reason = refused(lambda: live_write_denial_unit.run(fixture.ports(), arguments={}))

    assert reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert fixture.blocks.attempts == []


@pytest.mark.parametrize("use", ["mounted", "swap"])
def test_a_fixture_in_use_is_refused(use: str) -> None:
    mountinfo = "22 1 0:21 / / rw - overlay overlay rw\n30 22 253:2 / /mnt rw - ext4 /dev/vda2 rw\n"
    swaps = "Filename Type Size Used Priority\n/dev/vda2 partition 100 0 -2\n"
    fixture = guest(
        virtio_fixture(),
        mountinfo=mountinfo if use == "mounted" else "22 1 0:21 / / rw - overlay overlay rw\n",
        swaps=swaps if use == "swap" else "Filename Type Size Used Priority\n",
    )

    reason = refused(lambda: live_write_denial_unit.run(fixture.ports(), arguments={}))

    assert reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert fixture.blocks.attempts == []


def test_a_node_whose_identity_differs_from_sysfs_is_refused() -> None:
    fixture = guest(virtio_fixture())
    fixture.files.devices["/dev/vda2"] = files_port.DeviceNumber(253, 99)

    reason = refused(lambda: live_write_denial_unit.run(fixture.ports(), arguments={}))

    assert reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert fixture.blocks.attempts == []


def test_a_fixture_that_changes_between_attempts_is_refused() -> None:
    fixture = guest(virtio_fixture())
    files = fixture.files

    class Moving(fake_blockdevices.FakeBlockDevices):
        """A guest whose last fixture turns writable the moment the first write lands."""

        def rewrite(
            self,
            node: safepaths.SafePath,
            *,
            expected: files_port.DeviceNumber,
            offset: int,
            length: int,
        ) -> blockdevices.Rewrite:
            target = home_of(virtio_fixture()[4]) / "ro"
            files.write_atomic(target, b"0\n", mode=quantities.FileMode(0o444))
            return super().rewrite(node, expected=expected, offset=offset, length=length)

    moving = Moving()
    moving.nodes = fixture.blocks.nodes
    fixture.blocks = moving

    reason = refused(lambda: live_write_denial_unit.run(fixture.ports(), arguments={}))

    assert reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert len(moving.attempts) == 1


def test_outside_the_live_medium_the_fault_refuses_before_reading_sysfs() -> None:
    fixture = guest(virtio_fixture(), live=False)

    reason = refused(lambda: live_write_denial_unit.run(fixture.ports(), arguments={}))

    assert reason is refusals.RefusalReason.PROBE_ENVIRONMENT_UNEXPECTED
    assert fixture.blocks.attempts == []


def test_the_usb_fixture_is_settled_then_every_node_denied() -> None:
    fixture = guest(usb_fixture())

    report = usb_write_denial_unit.run(fixture.ports(), arguments={})

    assert report["status"] == "PASS"
    assert [tuple(call) for call in fixture.process.calls] == [
        ("systemd-detect-virt", "--vm"), ("udevadm", "settle", "--timeout=20"),
    ]
    assert [item.node for item in fixture.blocks.attempts] == [
        "/dev/sda", "/dev/sda1", "/dev/sda2", "/dev/sda3",
    ]
    assert report["physical_usb"] == "NOT TESTED"
    assert report["hotplug_race_window"] == "NOT TESTED"


def test_udev_not_settling_is_a_port_failure_before_any_read() -> None:
    fixture = guest(usb_fixture())
    fixture.process.expect(("udevadm", "settle", "--timeout=20"), fake_process.Reply(exit_code=1))

    with pytest.raises(errors.PortFailure):
        usb_write_denial_unit.run(fixture.ports(), arguments={})

    assert fixture.blocks.attempts == []


@pytest.mark.parametrize("change", ["wrong-serial", "no-serial", "extra-node", "not-usb"])
def test_a_usb_fixture_that_differs_is_refused_before_any_write(change: str) -> None:
    specs = usb_fixture()
    serial: str | None = "apex-usb-fixture"
    if change == "wrong-serial":
        serial = "someone-else"
    elif change == "no-serial":
        serial = None
    elif change == "extra-node":
        specs.append(DeviceSpec("sdb", 100, bus="usb1", major=8, minor=16))
    else:
        specs[0] = DeviceSpec("sda", 4 * 2**21, bus="virtio1", major=8, minor=0)
    fixture = guest(specs, usb_serial=serial)

    reason = refused(lambda: usb_write_denial_unit.run(fixture.ports(), arguments={}))

    assert reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert fixture.blocks.attempts == []


def test_the_report_names_the_fixture_inventory_it_wrote_to() -> None:
    fixture = guest(virtio_fixture())

    report = live_write_denial_unit.run(fixture.ports(), arguments={})

    inventory = report["inventory"]
    assert isinstance(inventory, list)
    names = [item["name"] for item in inventory if isinstance(item, dict)]
    assert names == ["vda", "vda1", "vda2", "vda3", "vdb"]
    assert livefixtures.overall([], expected=5) == "FAIL"
    assert Path("/dev/vda").name == "vda"

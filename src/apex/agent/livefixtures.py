"""The disk fixtures a live guest may write to, and the one write a fault makes to them.

A fixture is a disk the host attached for the test and nothing else: the older scripts named
them by size, serial, bus and partition layout, and refused to touch anything that differed.
The rules here are those, over one sysfs snapshot instead of a walk per device. The write is
the device's own first sector written back to it; the kernel's refusal is the result.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from collections.abc import Callable, Iterable
from pathlib import Path

from apex.agent import agentports, blockdevices
from apex.config import defaults
from apex.kernel import encoding, errors, refusals, safepaths

VIRTIO_NAME = re.compile(r"vd[a-z]+[0-9]*")
VIRTIO_BUS = re.compile(r"virtio[0-9]+")
USB_NAME = re.compile(r"sd[a-z]+[0-9]*")
USB_BUS = re.compile(r"usb[0-9]+")
ZRAM = re.compile(r"/dev/zram[0-9]+")
MOUNTINFO = safepaths.SafePath(Path("/proc/self/mountinfo"))
SWAPS = safepaths.SafePath(Path("/proc/swaps"))
DEVICES = Path("/dev")
SECTOR = 512
OTHER_SERIAL = "apex-other-1"
OTHER_SECTORS = 4 * 2**21
TARGET_SECTORS = 48 * 2**21
USB_SERIAL = "apex-usb-fixture"
USB_SECTORS = 4 * 2**21
PARTITIONS = frozenset({1, 2, 3})
PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
METHOD = "pwrite original 512 bytes at offset zero"


def refuse(detail: str) -> errors.Refusal:
    return errors.Refusal(
        refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED,
        subject=detail,
        remedy="keep the guest and inspect it; the fault writes only to the fixtures it expects",
    )


def _lines(ports: agentports.AgentPorts, path: safepaths.SafePath) -> list[str]:
    return ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value).decode().splitlines()


@dataclasses.dataclass(frozen=True, slots=True)
class Inventory:
    snapshot: blockdevices.Snapshot
    mounted: frozenset[str]
    swaps: frozenset[str]

    @classmethod
    def take(cls, ports: agentports.AgentPorts, *, matching: re.Pattern[str]) -> Inventory:
        """Every matching device, its node checked against sysfs, and what is in use."""
        snapshot = blockdevices.Snapshot.take(ports.files, matching=matching)
        for device in snapshot.devices:
            seen = ports.files.inspect(safepaths.SafePath(DEVICES / device.name))
            if seen.device != device.number:
                raise refuse(f"{device.name}: block node identity differs from sysfs")
        mounted = frozenset(line.split()[2] for line in _lines(ports, MOUNTINFO))
        swaps = frozenset(line.split()[0] for line in _lines(ports, SWAPS)[1:])
        if any(not ZRAM.fullmatch(name) for name in swaps):
            raise refuse("unexpected swap device")
        return cls(snapshot=snapshot, mounted=mounted, swaps=swaps)

    @property
    def devices(self) -> tuple[blockdevices.BlockDevice, ...]:
        return self.snapshot.devices

    def same_as(self, other: Inventory) -> bool:
        return self.snapshot.same_as(other.snapshot)

    def document(self) -> list[encoding.JsonValue]:
        return [device.document() for device in self.devices]

    def in_use(self, device: blockdevices.BlockDevice) -> bool:
        return (
            device.number.rendered in self.mounted
            or f"/dev/{device.name}" in self.swaps
            or bool(device.holders)
        )


def _require_protected(inventory: Inventory, name: re.Pattern[str], bus: re.Pattern[str]) -> None:
    for device in inventory.devices:
        if (
            not name.fullmatch(device.name)
            or not device.on_bus(bus)
            or not device.read_only
            or device.sectors < 1
            or inventory.in_use(device)
        ):
            raise refuse(f"{device.name} is writable, mounted, swapped, held or on another bus")


def require_live_fixture(inventory: Inventory) -> None:
    """The blank 48 GiB target and the partitioned 4 GiB sentinel, and nothing else."""
    whole = [item for item in inventory.devices if item.partition is None]
    parts = [item for item in inventory.devices if item.partition is not None]
    if (
        len(whole) != 2
        or len(parts) != 3
        or sorted(item.sectors for item in whole) != [OTHER_SECTORS, TARGET_SECTORS]
    ):
        raise refuse("expected only the blank 48 GiB and partitioned 4 GiB fixtures")
    other = next(item for item in whole if item.sectors == OTHER_SECTORS)
    if (
        other.serial != OTHER_SERIAL
        or {item.partition for item in parts} != PARTITIONS
        or any(item.parent != other.name for item in parts)
    ):
        raise refuse("fixture serial or partition topology differs")
    _require_protected(inventory, VIRTIO_NAME, VIRTIO_BUS)


def usb_parent(ports: agentports.AgentPorts, device: blockdevices.BlockDevice) -> str | None:
    """The USB device directory above the node that carries the fixture's serial, or none."""
    for parent in Path(device.sysfs_path).parents:
        home = safepaths.SafePath(parent)
        if not any(USB_BUS.fullmatch(part) for part in parent.parts):
            continue
        if not (ports.files.exists(home / "idVendor") and ports.files.exists(home / "idProduct")):
            continue
        try:
            serial = ports.files.read_bytes(home / "serial", limit=SECTOR).decode().strip()
        except (errors.PortFailure, UnicodeDecodeError):
            continue
        if serial == USB_SERIAL:
            return str(parent)
    return None


def require_usb_fixture(ports: agentports.AgentPorts, inventory: Inventory) -> None:
    """One 4 GiB USB fixture with three partitions, all on one USB device, all protected."""
    parents = {device.name: usb_parent(ports, device) for device in inventory.devices}
    if any(parent is None for parent in parents.values()):
        raise refuse("a matching node is not on the USB fixture")
    whole = [item for item in inventory.devices if item.partition is None]
    if (
        len(inventory.devices) != 4
        or len(whole) != 1
        or whole[0].sectors != USB_SECTORS
        or {item.partition for item in inventory.devices} != PARTITIONS | {None}
        or len(set(parents.values())) != 1
    ):
        raise refuse("expected one 4 GiB USB fixture with three partitions")
    _require_protected(inventory, USB_NAME, USB_BUS)


def attempt(ports: agentports.AgentPorts, device: blockdevices.BlockDevice) -> encoding.Document:
    """Write the first sector back to itself and say what the kernel did."""
    outcome = ports.blocks.rewrite(
        safepaths.SafePath(DEVICES / device.name), expected=device.number, offset=0, length=SECTOR
    )
    result: dict[str, encoding.JsonValue] = {
        "device": device.name,
        "status": FAIL,
        "method": METHOD,
        "before_sha256": hashlib.sha256(outcome.before).hexdigest(),
        "after_sha256": hashlib.sha256(outcome.after).hexdigest(),
    }
    if outcome.error_number is None:
        result["bytes_written"] = outcome.written
    else:
        result["errno"] = outcome.error_number
        result["status"] = PASS if outcome.denied else BLOCKED
    if not outcome.unchanged:
        result["status"] = FAIL
    return result


def exercise(
    ports: agentports.AgentPorts, inventory: Inventory, *, retake: Callable[[], Inventory]
) -> list[encoding.JsonValue]:
    """Every device in turn, stopping at the first that is not denied.

    The inventory is taken again before each attempt: a fixture that changed under the
    fault is refused, and the attempts already made are not reported as if they stood.
    """
    results: list[encoding.JsonValue] = []
    for device in inventory.devices:
        if not retake().same_as(inventory):
            raise refuse("fixture state changed during test")
        result = attempt(ports, device)
        results.append(result)
        if result["status"] != PASS:
            break
    return results


def overall(results: Iterable[encoding.JsonValue], *, expected: int) -> str:
    """PASS only when every expected device was denied; otherwise the first other status."""
    statuses = [str(item["status"]) for item in results if isinstance(item, dict)]
    if len(statuses) == expected and all(status == PASS for status in statuses):
        return PASS
    return next((status for status in statuses if status != PASS), FAIL)

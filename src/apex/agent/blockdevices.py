"""What sysfs says about every block device, read once and indexed.

The older probes walked `/sys/class/block` again for each device they touched, so a fixture
of n devices cost n squared reads. One snapshot reads each device's attributes once and then
answers by number or by name in constant time. A digest over the whole listing says whether
the tree changed between two snapshots, which is what the older scripts asked by comparing
two inventories.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from pathlib import Path

from apex.kernel import encoding, errors, hashing, identifiers, refusals, safepaths
from apex.ports import files

SYSFS_BLOCK = safepaths.SafePath(Path("/sys/class/block"))
ATTRIBUTE_LIMIT = 4096
HOLDERS = "holders"
SLAVES = "slaves"
OPTIONAL = ("partition", "serial", "device/serial")


@dataclasses.dataclass(frozen=True, slots=True)
class BlockDevice:
    name: str
    sysfs_path: str
    number: files.DeviceNumber
    read_only: bool
    sectors: int
    partition: int | None
    serial: str | None
    holders: tuple[str, ...]
    slaves: tuple[str, ...] | None

    @property
    def parent(self) -> str:
        """The device directory this one sits under: its disk for a partition."""
        return Path(self.sysfs_path).parent.name

    def on_bus(self, pattern: re.Pattern[str]) -> bool:
        return any(pattern.fullmatch(part) for part in Path(self.sysfs_path).parts)

    def document(self) -> encoding.Document:
        return {
            "name": self.name,
            "sysfs_path": self.sysfs_path,
            "dev": self.number.rendered,
            "ro": "1" if self.read_only else "0",
            "sectors": self.sectors,
            "partition": self.partition,
            "serial": self.serial,
            "holders": list(self.holders),
            "slaves": None if self.slaves is None else list(self.slaves),
        }


def _refuse(name: str, attribute: str, detail: str) -> errors.Refusal:
    return errors.Refusal(
        refusals.RefusalReason.SYSFS_ATTRIBUTE_MALFORMED,
        subject=f"{name}/{attribute}: {detail}",
        remedy="the device tree is not one this probe understands; keep the guest and look",
    )


def _read(port: files.FileSystemPort, entry: safepaths.SafePath, attribute: str) -> str | None:
    try:
        return port.read_bytes(entry / attribute, limit=ATTRIBUTE_LIMIT).decode().strip()
    except (errors.PortFailure, UnicodeDecodeError):
        return None


def _required(port: files.FileSystemPort, entry: safepaths.SafePath, attribute: str) -> str:
    value = _read(port, entry, attribute)
    if value is None:
        raise _refuse(entry.path.name, attribute, "absent or unreadable")
    return value


def _integer(name: str, attribute: str, text: str | None) -> int | None:
    if text is None:
        return None
    if not text.isdigit():
        raise _refuse(name, attribute, f"{text!r} is not a count")
    return int(text)


def _names(port: files.FileSystemPort, directory: safepaths.SafePath) -> tuple[str, ...] | None:
    try:
        return tuple(entry.relative for entry in port.list_directory(directory))
    except errors.PortFailure:
        return None


def _device(port: files.FileSystemPort, root: safepaths.SafePath, name: str) -> BlockDevice:
    entry = root / name
    resolved = port.resolve(entry)
    read_only = _required(port, entry, "ro")
    if read_only not in {"0", "1"}:
        raise _refuse(name, "ro", f"{read_only!r} is neither 0 nor 1")
    sectors = _integer(name, "size", _required(port, entry, "size"))
    if sectors is None:
        raise _refuse(name, "size", "absent")
    serial = _read(port, entry, "serial")
    device_serial = _read(port, entry, "device/serial")
    holders = _names(port, entry / HOLDERS)
    return BlockDevice(
        name=name,
        sysfs_path=str(resolved),
        number=files.DeviceNumber.parse(_required(port, entry, "dev")),
        read_only=read_only == "1",
        sectors=sectors,
        partition=_integer(name, "partition", _read(port, entry, "partition")),
        serial=serial if serial is not None else device_serial,
        holders=holders or (),
        slaves=_names(port, entry / SLAVES),
    )


@dataclasses.dataclass(frozen=True, slots=True)
class Snapshot:
    devices: tuple[BlockDevice, ...]
    generation: identifiers.Digest
    _by_name: Mapping[str, BlockDevice]
    _by_number: Mapping[files.DeviceNumber, BlockDevice]

    @classmethod
    def take(
        cls,
        port: files.FileSystemPort,
        *,
        root: safepaths.SafePath = SYSFS_BLOCK,
        matching: re.Pattern[str] | None = None,
    ) -> Snapshot:
        """Every device under the root, or only those whose name the pattern accepts."""
        names = sorted(entry.relative for entry in port.list_directory(root))
        devices = tuple(
            _device(port, root, name)
            for name in names
            if matching is None or matching.fullmatch(name)
        )
        listing = encoding.canonical([device.document() for device in devices])
        by_number = {device.number: device for device in devices}
        if len(by_number) != len(devices):
            raise errors.Refusal(
                refusals.RefusalReason.SYSFS_ATTRIBUTE_MALFORMED,
                subject="two devices share one number",
                remedy="the device tree is not one this probe understands; keep the guest and look",
            )
        return cls(
            devices=devices,
            generation=hashing.digest_bytes(listing),
            _by_name={device.name: device for device in devices},
            _by_number=by_number,
        )

    def by_name(self, name: str) -> BlockDevice | None:
        return self._by_name.get(name)

    def by_number(self, number: files.DeviceNumber) -> BlockDevice | None:
        return self._by_number.get(number)

    def same_as(self, other: Snapshot) -> bool:
        return self.generation == other.generation

    def document(self) -> encoding.Document:
        return {device.name: device.document() for device in self.devices}

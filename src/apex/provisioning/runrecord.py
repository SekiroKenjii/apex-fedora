"""What a test run was started from, kept beside its overlays for the comparison and the resumption.

The lease says how the machine was started; this says what it was started from: the source
each overlay layers, the image it booted and its medium, and the switches the request
carried. A comparison reads it to know which source stands behind each overlay, and a
resumption rebuilds the same machine over the same overlays from it. Like the lease, it is
never deleted.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Self

from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.model import machines
from apex.ports import portset
from apex.provisioning import leases

SCHEMA = 1


@dataclasses.dataclass(frozen=True, slots=True)
class Layer:
    source: Path
    overlay: Path

    def document(self) -> encoding.Document:
        return {"source": str(self.source), "overlay": str(self.overlay)}

    @classmethod
    def parse(cls, entry: object) -> Self:
        if not isinstance(entry, Mapping):
            raise TypeError("layer")
        return cls(source=Path(str(entry["source"])), overlay=Path(str(entry["overlay"])))


@dataclasses.dataclass(frozen=True, slots=True)
class RunRecord:
    run: identifiers.RunId
    disk: Layer
    extras: tuple[Layer, ...]
    iso: Path | None
    medium: machines.Medium | None
    guest_ssh: bool
    serial_console: bool
    usb_bus: bool
    boot_usb: Layer | None

    def document(self) -> encoding.Document:
        return {
            "schema": SCHEMA,
            "run": str(self.run),
            "disk": self.disk.document(),
            "extras": [item.document() for item in self.extras],
            "iso": None if self.iso is None else str(self.iso),
            "medium": None if self.medium is None else str(self.medium),
            "guest_ssh": self.guest_ssh,
            "serial_console": self.serial_console,
            "usb_bus": self.usb_bus,
            "boot_usb": None if self.boot_usb is None else self.boot_usb.document(),
        }

    @classmethod
    def parse(cls, document: Mapping[str, object]) -> Self:
        try:
            extras = document["extras"]
            if not isinstance(extras, list):
                raise TypeError("extras")
            iso, medium = document.get("iso"), document.get("medium")
            boot = document.get("boot_usb")
            return cls(
                run=identifiers.RunId.parse(str(document["run"])),
                disk=Layer.parse(document["disk"]),
                extras=tuple(Layer.parse(item) for item in extras),
                iso=None if iso is None else Path(str(iso)),
                medium=None if medium is None else machines.Medium(str(medium)),
                guest_ssh=bool(document["guest_ssh"]),
                serial_console=bool(document["serial_console"]),
                usb_bus=bool(document["usb_bus"]),
                boot_usb=None if boot is None else Layer.parse(boot),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise errors.Refusal(
                refusals.RefusalReason.LEASE_MALFORMED,
                subject=f"{defaults.RUN_RECORD_NAME}: {error}",
            ) from error

    def layers(self, hotplug: Layer | None = None) -> tuple[Layer, ...]:
        """Every overlay the run wrote, with its source, the hot-plugged fixture last."""
        found = [self.disk, *self.extras]
        if self.boot_usb is not None:
            found.append(self.boot_usb)
        if hotplug is not None:
            found.append(hotplug)
        return tuple(found)


def write(ports: portset.HostPorts, run_directory: safepaths.SafePath, record: RunRecord) -> None:
    leases.write_record(
        ports, safepaths.SafePath(run_directory.path / defaults.RUN_RECORD_NAME), record.document()
    )


def read(ports: portset.HostPorts, run_directory: safepaths.SafePath) -> RunRecord:
    path = safepaths.SafePath(run_directory.path / defaults.RUN_RECORD_NAME)
    if not ports.files.exists(path):
        raise errors.Refusal(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject=f"{path}: the run left no record of what it was started from",
            remedy="only a run this tree started can be compared or resumed",
        )
    try:
        loaded = json.loads(ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value))
    except json.JSONDecodeError as error:
        raise errors.Refusal(
            refusals.RefusalReason.LEASE_MALFORMED, subject=f"{path.path.name}: {error.msg}"
        ) from error
    if not isinstance(loaded, dict):
        raise errors.Refusal(
            refusals.RefusalReason.LEASE_MALFORMED, subject=f"{path.path.name}: not an object"
        )
    return RunRecord.parse(loaded)

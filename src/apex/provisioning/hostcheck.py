"""What the host has and what a machine needs, read through the ports and said in one report.

The older `doctor` printed its findings and then refused on the first shortfall; the report
here carries every finding, so the operator reads all of it, and the problems are listed
in the order the older tool checked them: the tools and the firmware, then the capacity.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path

from apex.config import defaults, loader
from apex.kernel import encoding, errors, quantities, refusals, safepaths
from apex.ports import portset
from apex.provisioning import launching, leases


@dataclasses.dataclass(frozen=True, slots=True)
class Report:
    tools: dict[str, Path | None]
    kvm: bool
    available_memory_mib: int
    required_memory_mib: int
    free_gib: int
    required_free_gib: int
    state: Path
    running: leases.MachineLease | None
    firmware: bool

    def document(self) -> encoding.Document:
        return {
            "tools": {
                name: None if path is None else str(path) for name, path in self.tools.items()
            },
            "kvm": self.kvm,
            "available_memory_mib": self.available_memory_mib,
            "required_memory_mib": self.required_memory_mib,
            "free_gib": self.free_gib,
            "required_free_gib": self.required_free_gib,
            "state": str(self.state),
            "vm": None if self.running is None else self.running.document(),
            "firmware": self.firmware,
        }

    def problems(self) -> tuple[errors.Refusal, ...]:
        """Every shortfall as the refusal it would be, in the order the older tool checked."""
        found: list[errors.Refusal] = []
        missing = sorted(name for name, path in self.tools.items() if path is None)
        if missing:
            found.append(
                errors.Refusal(
                    refusals.RefusalReason.HOST_TOOL_MISSING,
                    subject=", ".join(missing),
                    remedy="install the missing tools",
                )
            )
        if not self.firmware:
            found.append(
                errors.Refusal(
                    refusals.RefusalReason.FIRMWARE_ABSENT,
                    subject="the OVMF firmware the settings name",
                    remedy="install the firmware or point the settings at it",
                )
            )
        shortfalls = {
            f"{self.required_memory_mib} MiB of memory including the host reserve; found "
            f"{self.available_memory_mib} MiB": (
                self.available_memory_mib < self.required_memory_mib
            ),
            f"{self.required_free_gib} GiB free in the runtime directory; found "
            f"{self.free_gib} GiB": self.free_gib < self.required_free_gib,
            "access to the kvm device": not self.kvm,
        }
        found.extend(
            errors.Refusal(refusals.RefusalReason.HOST_CAPACITY_INSUFFICIENT, subject=subject)
            for subject, short in shortfalls.items()
            if short
        )
        return tuple(found)


def examine(
    ports: portset.HostPorts,
    settings: loader.Settings,
    root: safepaths.RuntimeRoot,
    *,
    tools: Sequence[str] = defaults.HOST_TOOLS,
) -> Report:
    builder = settings.builder
    capacity = ports.hypervisor.capacity(root)
    return Report(
        tools={name: ports.processes.locate(name) for name in tools},
        kvm=capacity.kvm_accessible,
        available_memory_mib=capacity.available_memory.value,
        required_memory_mib=(builder.memory + builder.reserve).value,
        free_gib=capacity.free_space.value // quantities.BYTES_PER_GIBIBYTE,
        required_free_gib=builder.minimum_free.value,
        state=root.path,
        running=launching.current(ports, root=root),
        firmware=all(
            ports.files.exists(safepaths.SafePath(path))
            for path in (builder.firmware_code, builder.firmware_variables)
        ),
    )

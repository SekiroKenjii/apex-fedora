"""What a disposable run changed, read from the disks and the firmware variables.

Every overlay is compared with its source in full, and the firmware variables a run started
with are compared with what it left behind. The older tree wrote the clean variable baseline
and never read it; here the comparison is the reason it is written.
"""

from __future__ import annotations

import dataclasses

from apex.config import defaults
from apex.kernel import commands, encoding, errors, refusals, safepaths
from apex.ports import portset
from apex.provisioning import backingchain, launching, leases

UNCHANGED = 0
CHANGED = 1
METHOD = "qemu-img compare: complete guest-visible disk contents"


@dataclasses.dataclass(frozen=True, slots=True)
class Layered:
    source: backingchain.BackingChain
    overlay: backingchain.BackingChain


@dataclasses.dataclass(frozen=True, slots=True)
class DiskObservation:
    source: safepaths.SafePath
    overlay: safepaths.SafePath
    unchanged: bool
    output: str


@dataclasses.dataclass(frozen=True, slots=True)
class RunComparison:
    disks: tuple[DiskObservation, ...]
    variables_unchanged: bool

    def document(self) -> encoding.Document:
        return {
            "method": METHOD,
            "disks": [
                {
                    "source": str(item.source),
                    "overlay": str(item.overlay),
                    "unchanged": item.unchanged,
                    "output": item.output,
                }
                for item in self.disks
            ],
            "firmware_variables_unchanged": self.variables_unchanged,
        }


def compare(
    ports: portset.HostPorts,
    *,
    root: safepaths.RuntimeRoot,
    run_directory: safepaths.SafePath,
    disks: tuple[Layered, ...],
) -> RunComparison:
    if launching.current(ports, root=root) is not None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_RUNNING,
            subject="a machine is running",
            remedy="stop every machine before comparing its disks",
        )
    observations = tuple(_compare_one(ports, item) for item in disks)
    initial = ports.files.read_bytes(
        safepaths.SafePath(run_directory.path / defaults.INITIAL_VARIABLES_NAME),
        limit=defaults.FIRMWARE_VARIABLES_LIMIT.value,
    )
    final = ports.files.read_bytes(
        safepaths.SafePath(run_directory.path / defaults.VARIABLES_NAME),
        limit=defaults.FIRMWARE_VARIABLES_LIMIT.value,
    )
    comparison = RunComparison(disks=observations, variables_unchanged=initial == final)
    leases.write_record(
        ports,
        safepaths.SafePath(run_directory.path / defaults.COMPARISON_RECORD),
        comparison.document(),
    )
    return comparison


def _compare_one(ports: portset.HostPorts, item: Layered) -> DiskObservation:
    completed = ports.processes.run(
        commands.Argv.of(
            backingchain.QEMU_IMG, "compare", "-f", backingchain.QCOW2, "-F",
            backingchain.QCOW2, item.source.disk, item.overlay.disk,
        ),
        deadline=defaults.IMAGE_TOOL_DEADLINE,
        limit=commands.OutputLimit.default(),
    )
    if completed.exit_code not in (UNCHANGED, CHANGED):
        raise errors.PortFailure(
            port=backingchain.QEMU_IMG, cause=completed.stderr.decode(errors="replace").strip()
        )
    return DiskObservation(
        source=item.source.disk,
        overlay=item.overlay.disk,
        unchanged=completed.exit_code == UNCHANGED,
        output=completed.stdout.decode(errors="replace").strip(),
    )

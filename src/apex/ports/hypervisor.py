"""Starting and stopping a virtual machine process.

The port takes a rendered machine, never an argument list assembled elsewhere, and answers
with an identity of four fields. Stopping is refused unless every field still matches, so a
process identifier the kernel has since handed to something else cannot be signalled.
"""

from __future__ import annotations

import dataclasses
from typing import Protocol

from apex.kernel import claims, quantities, safepaths, timing
from apex.model import machines


@dataclasses.dataclass(frozen=True, slots=True)
class HostCapacity:
    available_memory: quantities.Mib
    free_space: quantities.ByteCount
    kvm_accessible: bool


class HypervisorPort(Protocol):
    environment: claims.EnvironmentKind

    def capacity(self, root: safepaths.RuntimeRoot) -> HostCapacity: ...

    def spawn(
        self,
        spec: machines.VmSpec,
        *,
        monitor: safepaths.SafePath,
        log: safepaths.SafePath,
        deadline: timing.Deadline,
    ) -> machines.VmIdentity:
        """Detach the machine and answer once its monitor socket exists.

        The deadline bounds only that wait. A process that exits before the socket appears
        is a port failure that names the log.
        """
        ...

    def running(self, identity: machines.VmIdentity) -> bool: ...

    def terminate(self, identity: machines.VmIdentity) -> None:
        """Kill the process, after checking that it is still the one the identity names."""
        ...

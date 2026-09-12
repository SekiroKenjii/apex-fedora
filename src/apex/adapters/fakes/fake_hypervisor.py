"""A hypervisor that records what it was asked to start and never starts anything."""

from __future__ import annotations

import dataclasses

from apex.kernel import claims, errors, quantities, refusals, safepaths, timing
from apex.model import machines
from apex.ports import hypervisor

AMPLE = hypervisor.HostCapacity(
    available_memory=quantities.Mib(16384),
    free_space=quantities.Gib(500).as_bytes(),
    kvm_accessible=True,
)


@dataclasses.dataclass(frozen=True, slots=True)
class Spawned:
    spec: machines.VmSpec
    monitor: safepaths.SafePath
    log: safepaths.SafePath
    identity: machines.VmIdentity


class FakeQemu(hypervisor.HypervisorPort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(
        self, *, capacity: hypervisor.HostCapacity = AMPLE, exits_at_once: bool = False
    ) -> None:
        self._capacity = capacity
        self.exits_at_once = exits_at_once
        self._issued = 0
        self._alive: dict[int, machines.VmIdentity] = {}
        self.spawned: list[Spawned] = []
        self.terminated: list[machines.VmIdentity] = []

    def capacity(self, root: safepaths.RuntimeRoot) -> hypervisor.HostCapacity:  # noqa: ARG002
        return self._capacity

    def spawn(
        self,
        spec: machines.VmSpec,
        *,
        monitor: safepaths.SafePath,
        log: safepaths.SafePath,
        deadline: timing.Deadline,
    ) -> machines.VmIdentity:
        if self.exits_at_once:
            raise errors.PortFailure(
                port="hypervisor", cause=f"{machines.QEMU_PROGRAM} exited with 1; see {log}"
            )
        self._issued += 1
        identity = machines.VmIdentity(
            process=1000 + self._issued,
            pidfd_inode=2000 + self._issued,
            boot_ticks=int(deadline.budget.seconds) + self._issued,
            monitor_socket_inode=3000 + self._issued,
        )
        self._alive[identity.process] = identity
        self.spawned.append(Spawned(spec=spec, monitor=monitor, log=log, identity=identity))
        return identity

    def exit(self, identity: machines.VmIdentity) -> None:
        """The guest halted on its own, as after a clean shutdown."""
        self._alive.pop(identity.process, None)

    def running(self, identity: machines.VmIdentity) -> bool:
        return self._alive.get(identity.process) == identity

    def terminate(self, identity: machines.VmIdentity) -> None:
        current = self._alive.get(identity.process)
        if current is None:
            raise errors.Refusal(
                refusals.RefusalReason.MACHINE_NOT_RUNNING,
                subject=f"process {identity.process}: No such process",
            )
        if current != identity:
            raise errors.Refusal(
                refusals.RefusalReason.MACHINE_IDENTITY_CHANGED,
                subject=f"process {identity.process} is not the machine that was started",
                remedy="the identifier was reused; nothing was signalled",
            )
        del self._alive[identity.process]
        self.terminated.append(identity)

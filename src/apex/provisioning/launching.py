"""Starting one machine, stopping it, and reclaiming one that was left behind.

The order is the safety: the lock is taken, the intent is written, and only then is the
process started. A host that dies between the two leaves an intent without a lease, which
`reclaim` reads. Stopping asks the guest first and kills only after the identity is checked
again, so a process number the kernel reused is never signalled.
"""

from __future__ import annotations

import dataclasses
import enum

from apex.config import defaults
from apex.kernel import claims, encoding, errors, identifiers, refusals, safepaths
from apex.model import machines
from apex.ports import locking, portset, qmp
from apex.provisioning import leases

MACHINE = locking.LockScope(defaults.MACHINE_LOCK)
POWERDOWN = qmp.QmpCommand("system_powerdown")


class Ending(enum.StrEnum):
    STOPPED = "stopped"
    KILLED = "killed"


@dataclasses.dataclass(frozen=True, slots=True)
class Reclaimed:
    intent: leases.MachineIntent | None
    lease: leases.MachineLease | None
    orphaned: bool


def launch(
    ports: portset.HostPorts,
    *,
    root: safepaths.RuntimeRoot,
    spec: machines.VmSpec,
    run: identifiers.RunId,
    run_directory: safepaths.SafePath,
    medium: machines.Medium | None = None,
) -> leases.MachineLease:
    with ports.locks.acquire(MACHINE, locking.AcquisitionPolicy.immediate()):
        _require_no_machine(ports, root=root)
        _require_capacity(ports, root=root, resources=spec.resources)
        monitor = root.child(defaults.MONITOR_SOCKET_NAME)
        intent = leases.MachineIntent(
            role=spec.role,
            run=run,
            run_directory=run_directory,
            monitor=monitor,
            command=spec.render(),
            written_at=ports.clock.stamp(),
            witness=witness_of(ports, spec.role, medium),
        )
        leases.write_intent(ports, intent, root=root)
        identity = ports.hypervisor.spawn(
            spec,
            monitor=monitor,
            log=safepaths.SafePath(run_directory.path / defaults.HYPERVISOR_LOG_NAME),
            deadline=defaults.MONITOR_APPEARS,
        )
        lease = leases.MachineLease(intent=intent, identity=identity)
        leases.write_lease(ports, lease, root=root)
        return lease


def witness_of(
    ports: portset.HostPorts, role: machines.VmRole, medium: machines.Medium | None = None
) -> claims.EnvironmentKind:
    """What the launching adapter can vouch for: nothing when simulated, else the role and
    the medium a disposable machine was booted from."""
    if ports.hypervisor.environment is claims.EnvironmentKind.SIMULATED:
        return claims.EnvironmentKind.SIMULATED
    if role is machines.VmRole.BUILDER:
        return claims.EnvironmentKind.BUILD
    if medium is machines.Medium.LIVE:
        return claims.EnvironmentKind.LIVE_VM
    if medium is machines.Medium.INSTALLER:
        return claims.EnvironmentKind.INSTALLER_VM
    return claims.EnvironmentKind.VM


def current(ports: portset.HostPorts, *, root: safepaths.RuntimeRoot) -> leases.MachineLease | None:
    """The lease of the machine that is running now, or nothing."""
    lease = leases.read_lease(ports, root=root)
    if lease is None or lease.released or not ports.hypervisor.running(lease.identity):
        return None
    return lease


def shutdown(
    ports: portset.HostPorts, lease: leases.MachineLease, *, root: safepaths.RuntimeRoot
) -> Ending:
    with ports.locks.acquire(MACHINE, locking.AcquisitionPolicy.immediate()):
        if not ports.hypervisor.running(lease.identity):
            raise errors.Refusal(
                refusals.RefusalReason.MACHINE_NOT_RUNNING,
                subject=f"process {lease.identity.process} is not the machine this lease names",
                remedy="reclaim the runtime root instead of stopping a machine that is gone",
            )
        with ports.monitor.connect(lease.intent.monitor, deadline=defaults.QMP_DEADLINE) as session:
            session.execute(POWERDOWN)
        try:
            ports.clock.wait_until(
                lambda: not ports.hypervisor.running(lease.identity), defaults.SHUTDOWN
            )
            ending = Ending.STOPPED
        except errors.PortFailure:
            ports.hypervisor.terminate(lease.identity)
            ending = Ending.KILLED
        leases.write_lease(ports, lease.release(), root=root)
        return ending


def power_loss(
    ports: portset.HostPorts,
    owned: machines.OwnedTestVm,
    lease: leases.MachineLease,
    *,
    root: safepaths.RuntimeRoot,
) -> None:
    """Kill a disposable machine outright, recording the fault before the signal."""
    with ports.locks.acquire(MACHINE, locking.AcquisitionPolicy.immediate()):
        if owned.identity != lease.identity or lease.intent.role is not owned.role:
            raise errors.Refusal(
                refusals.RefusalReason.LEASE_MISMATCH,
                subject="the owned machine is not the one the lease names",
            )
        record: encoding.Document = {
            "fault": "guest-power-loss",
            "process": lease.identity.process,
            "host_rebooted": False,
            "simulates_physical_storage_power_loss": False,
            "recorded_at": ports.clock.stamp().rendered,
        }
        target = safepaths.SafePath(lease.intent.run_directory.path / defaults.POWER_LOSS_RECORD)
        leases.write_record(ports, target, record)
        ports.hypervisor.terminate(lease.identity)
        leases.write_lease(ports, lease.release(), root=root)


def reclaim(ports: portset.HostPorts, *, root: safepaths.RuntimeRoot) -> Reclaimed:
    """What the runtime root says was started, and whether anything is still running."""
    with ports.locks.acquire(MACHINE, locking.AcquisitionPolicy.immediate()):
        intent = leases.read_intent(ports, root=root)
        lease = leases.read_lease(ports, root=root)
        started_without_lease = intent is not None and (
            lease is None or lease.intent.run != intent.run
        )
        stale_lease = (
            lease is not None
            and not lease.released
            and not ports.hypervisor.running(lease.identity)
        )
        if stale_lease and lease is not None:
            leases.write_lease(ports, lease.release(), root=root)
        return Reclaimed(intent=intent, lease=lease, orphaned=started_without_lease or stale_lease)


def _require_no_machine(ports: portset.HostPorts, *, root: safepaths.RuntimeRoot) -> None:
    running = current(ports, root=root)
    if running is not None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_RUNNING,
            subject=f"a {running.intent.role} machine, process {running.identity.process}",
            remedy="only one machine runs at a time; stop it first",
        )


def _require_capacity(
    ports: portset.HostPorts, *, root: safepaths.RuntimeRoot, resources: machines.VmResources
) -> None:
    capacity = ports.hypervisor.capacity(root)
    needed = resources.memory + defaults.BUILDER.reserve
    shortfalls = {
        f"{needed.value} MiB of memory": capacity.available_memory < needed,
        f"{defaults.TEST_MACHINE_MINIMUM_FREE.value} GiB free below the runtime root": (
            capacity.free_space < defaults.TEST_MACHINE_MINIMUM_FREE.as_bytes()
        ),
        "access to the kvm device": not capacity.kvm_accessible,
    }
    for subject, short in shortfalls.items():
        if short:
            raise errors.PreconditionUnmet(
                refusals.RefusalReason.HOST_CAPACITY_INSUFFICIENT, subject=subject
            )

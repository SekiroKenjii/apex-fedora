"""The lock, the intent, the process, in that order; and the guest asked before it is killed."""

from __future__ import annotations

import dataclasses

import pytest
from machinehost import RUN, Host

from apex.adapters.fakes import fake_hypervisor
from apex.config import defaults
from apex.kernel import claims, errors, quantities, refusals, timing
from apex.model import machines
from apex.ports import hypervisor as hypervisor_port
from apex.ports import locking
from apex.provisioning import launching, leases


def start(host: Host, role: machines.VmRole = machines.VmRole.TEST) -> leases.MachineLease:
    return launching.launch(
        host.ports, root=host.root, spec=host.spec(role), run=RUN, run_directory=host.run_directory
    )


def test_a_launch_writes_the_intent_then_the_lease(host: Host) -> None:
    lease = start(host)

    intent_index = host.files.writes.index(str(host.root.child(defaults.INTENT_NAME)))
    lease_index = host.files.writes.index(str(host.root.child(defaults.LEASE_NAME)))
    assert intent_index < lease_index
    assert lease.identity == host.hypervisor.spawned[0].identity
    assert leases.read_lease(host.ports, root=host.root) == lease


def test_the_intent_is_on_disk_before_the_process_is_started(host: Host) -> None:
    host.hypervisor.exits_at_once = True

    with pytest.raises(errors.PortFailure):
        start(host)

    assert leases.read_intent(host.ports, root=host.root) is not None
    assert leases.read_lease(host.ports, root=host.root) is None


def test_the_intent_records_the_command_the_hypervisor_was_given(host: Host) -> None:
    lease = start(host)

    assert lease.intent.command == host.hypervisor.spawned[0].spec.render()
    assert lease.intent.monitor == host.hypervisor.spawned[0].monitor


def test_a_second_machine_is_refused_while_one_runs(host: Host) -> None:
    start(host)

    with pytest.raises(errors.Refusal) as raised:
        start(host, machines.VmRole.BUILDER)

    assert raised.value.reason is refusals.RefusalReason.MACHINE_RUNNING
    assert len(host.hypervisor.spawned) == 1


def test_a_launch_needs_the_machine_lock(host: Host) -> None:
    scope = locking.LockScope(defaults.MACHINE_LOCK)
    with (
        host.locks.acquire(scope, locking.AcquisitionPolicy.immediate()),
        pytest.raises(errors.Refusal) as raised,
    ):
        start(host)

    assert raised.value.reason is refusals.RefusalReason.LOCK_HELD
    assert host.hypervisor.spawned == []


@pytest.mark.parametrize(
    "capacity",
    [
        hypervisor_port.HostCapacity(
            available_memory=quantities.Mib(1024),
            free_space=quantities.Gib(500).as_bytes(),
            kvm_accessible=True,
        ),
        hypervisor_port.HostCapacity(
            available_memory=quantities.Mib(16384),
            free_space=quantities.Gib(1).as_bytes(),
            kvm_accessible=True,
        ),
        hypervisor_port.HostCapacity(
            available_memory=quantities.Mib(16384),
            free_space=quantities.Gib(500).as_bytes(),
            kvm_accessible=False,
        ),
    ],
)
def test_a_host_short_of_capacity_is_a_precondition_and_writes_no_intent(
    host: Host, capacity: hypervisor_port.HostCapacity
) -> None:
    host.hypervisor._capacity = capacity  # noqa: SLF001

    with pytest.raises(errors.PreconditionUnmet) as raised:
        start(host)

    assert raised.value.reason is refusals.RefusalReason.HOST_CAPACITY_INSUFFICIENT
    assert host.files.writes == []


def test_current_names_the_running_machine_and_nothing_after_it_stops(host: Host) -> None:
    lease = start(host)

    assert launching.current(host.ports, root=host.root) == lease
    host.hypervisor.exit(lease.identity)
    assert launching.current(host.ports, root=host.root) is None


def test_a_guest_that_halts_when_asked_is_stopped(host: Host) -> None:
    lease = start(host)
    host.monitor.react("system_powerdown", lambda: host.hypervisor.exit(lease.identity))

    ending = launching.shutdown(host.ports, lease, root=host.root)

    assert ending is launching.Ending.STOPPED
    assert [command.name for command in host.monitor.executed] == ["system_powerdown"]
    assert host.hypervisor.terminated == []
    assert launching.current(host.ports, root=host.root) is None


def test_a_guest_that_ignores_the_request_is_killed_after_the_budget(host: Host) -> None:
    lease = start(host)

    ending = launching.shutdown(host.ports, lease, root=host.root)

    assert ending is launching.Ending.KILLED
    assert host.hypervisor.terminated == [lease.identity]
    slept = sum(span.seconds for span in host.clock.slept)
    assert slept >= defaults.SHUTDOWN.deadline.budget.seconds


def test_a_lease_whose_identity_changed_stops_nothing(host: Host) -> None:
    lease = start(host)
    reused = machines.VmIdentity(
        process=lease.identity.process,
        pidfd_inode=lease.identity.pidfd_inode,
        boot_ticks=lease.identity.boot_ticks + 1,
        monitor_socket_inode=lease.identity.monitor_socket_inode,
    )
    stale = leases.MachineLease(intent=lease.intent, identity=reused)

    with pytest.raises(errors.Refusal) as raised:
        launching.shutdown(host.ports, stale, root=host.root)

    assert raised.value.reason is refusals.RefusalReason.MACHINE_NOT_RUNNING
    assert host.monitor.executed == []
    assert host.hypervisor.running(lease.identity)


def test_power_loss_records_the_fault_before_the_signal(host: Host) -> None:
    lease = start(host)
    owned = machines.OwnedTestVm(identity=lease.identity, role=machines.VmRole.TEST)

    launching.power_loss(host.ports, owned, lease, root=host.root)

    record = str(host.run_directory.path / defaults.POWER_LOSS_RECORD)
    assert record in host.files.writes
    assert host.hypervisor.terminated == [lease.identity]
    assert host.files.writes.index(record) < len(host.files.writes) - 1
    assert launching.current(host.ports, root=host.root) is None


def test_power_loss_refuses_an_owner_that_is_not_the_lease(host: Host) -> None:
    lease = start(host)
    other = machines.VmIdentity(process=1, pidfd_inode=2, boot_ticks=3, monitor_socket_inode=4)
    owned = machines.OwnedTestVm(identity=other, role=machines.VmRole.TEST)

    with pytest.raises(errors.Refusal) as raised:
        launching.power_loss(host.ports, owned, lease, root=host.root)

    assert raised.value.reason is refusals.RefusalReason.LEASE_MISMATCH
    assert host.hypervisor.terminated == []


def test_power_loss_cannot_be_asked_of_a_builder(host: Host) -> None:
    lease = start(host, machines.VmRole.BUILDER)

    with pytest.raises(errors.Refusal) as raised:
        machines.OwnedTestVm(identity=lease.identity, role=lease.intent.role)

    assert raised.value.reason is refusals.RefusalReason.NOT_A_DISPOSABLE_MACHINE


def test_an_intent_without_a_lease_is_reclaimed_as_an_orphan(host: Host) -> None:
    host.hypervisor.exits_at_once = True
    with pytest.raises(errors.PortFailure):
        start(host)

    reclaimed = launching.reclaim(host.ports, root=host.root)

    assert reclaimed.orphaned
    assert reclaimed.intent is not None
    assert reclaimed.lease is None


def test_a_lease_whose_process_is_gone_is_released_by_reclaim(host: Host) -> None:
    lease = start(host)
    host.hypervisor.exit(lease.identity)

    reclaimed = launching.reclaim(host.ports, root=host.root)

    assert reclaimed.orphaned
    stored = leases.read_lease(host.ports, root=host.root)
    assert stored is not None
    assert stored.released


def test_a_running_machine_is_not_an_orphan(host: Host) -> None:
    start(host)

    reclaimed = launching.reclaim(host.ports, root=host.root)

    assert not reclaimed.orphaned


def test_an_empty_runtime_root_reclaims_nothing(host: Host) -> None:
    reclaimed = launching.reclaim(host.ports, root=host.root)

    assert reclaimed == launching.Reclaimed(intent=None, lease=None, orphaned=False)


def test_the_monitor_wait_is_bounded_by_the_declared_deadline(host: Host) -> None:
    start(host)

    assert isinstance(host.hypervisor, fake_hypervisor.FakeQemu)
    assert (
        host.hypervisor.spawned[0].identity.boot_ticks
        == int(defaults.MONITOR_APPEARS.budget.seconds) + 1
    )
    assert isinstance(defaults.MONITOR_APPEARS, timing.Deadline)


def test_a_fake_hypervisor_witnesses_only_a_simulation(host: Host) -> None:
    lease = start(host)

    assert lease.intent.witness is claims.EnvironmentKind.SIMULATED


@pytest.mark.parametrize(
    "role,expected",
    [
        (machines.VmRole.BUILDER, claims.EnvironmentKind.BUILD),
        (machines.VmRole.TEST, claims.EnvironmentKind.VM),
    ],
)
def test_a_real_hypervisor_witnesses_by_the_role(
    host: Host, role: machines.VmRole, expected: claims.EnvironmentKind
) -> None:
    declared_real = type(
        "RealQemu", (fake_hypervisor.FakeQemu,), {"environment": claims.EnvironmentKind.BUILD}
    )()
    ports = dataclasses.replace(host.ports, hypervisor=declared_real)

    assert launching.witness_of(ports, role) is expected


@pytest.mark.parametrize(
    "medium,expected",
    [
        (machines.Medium.LIVE, claims.EnvironmentKind.LIVE_VM),
        (machines.Medium.INSTALLER, claims.EnvironmentKind.INSTALLER_VM),
        (None, claims.EnvironmentKind.VM),
    ],
)
def test_a_test_machine_is_witnessed_by_the_medium_it_booted_from(
    host: Host, medium: machines.Medium | None, expected: claims.EnvironmentKind
) -> None:
    declared_real = type(
        "RealQemu", (fake_hypervisor.FakeQemu,), {"environment": claims.EnvironmentKind.BUILD}
    )()
    ports = dataclasses.replace(host.ports, hypervisor=declared_real)

    assert launching.witness_of(ports, machines.VmRole.TEST, medium) is expected

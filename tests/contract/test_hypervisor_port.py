"""Starting a machine and stopping only the machine that was started.

The real adapter runs a stand-in on the path that opens the monitor socket and waits, so the
process mechanics are exercised without a guest. A guest that boots is the integration tier.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import fake_hypervisor
from apex.config import defaults
from apex.kernel import errors, quantities, refusals, safepaths
from apex.model import machines
from apex.ports import hypervisor as hypervisor_port


def present(root: safepaths.RuntimeRoot, relative: str) -> safepaths.SafePath:
    target = root.path / relative
    target.write_bytes(b"")
    return safepaths.SafePath.regular_file(target, within=root)


def spec(root: safepaths.RuntimeRoot) -> machines.VmSpec:
    return machines.VmSpec.build(
        role=machines.VmRole.TEST,
        resources=machines.VmResources(memory=quantities.Mib(512), processors=1),
        root_disk=present(root, "disk.qcow2"),
        firmware=machines.Firmware(
            code=present(root, "code.fd"), variables=present(root, "vars.fd")
        ),
        monitor=machines.MonitorSocket(root.child("qmp.sock")),
        serial=machines.SerialFile(root.child("serial.log")),
    )


def start(
    hypervisors: hypervisor_port.HypervisorPort, root: safepaths.RuntimeRoot
) -> machines.VmIdentity:
    return hypervisors.spawn(
        spec(root),
        monitor=root.child("qmp.sock"),
        log=root.child("qemu.log"),
        deadline=defaults.MONITOR_APPEARS,
    )


def test_a_spawned_machine_is_running(
    hypervisors: hypervisor_port.HypervisorPort, root: safepaths.RuntimeRoot
) -> None:
    identity = start(hypervisors, root)
    try:
        assert hypervisors.running(identity)
    finally:
        hypervisors.terminate(identity)


def test_a_terminated_machine_is_not_running(
    hypervisors: hypervisor_port.HypervisorPort, root: safepaths.RuntimeRoot
) -> None:
    identity = start(hypervisors, root)

    hypervisors.terminate(identity)

    assert not hypervisors.running(identity)


def test_an_identity_that_no_longer_matches_is_refused_and_nothing_is_signalled(
    hypervisors: hypervisor_port.HypervisorPort, root: safepaths.RuntimeRoot
) -> None:
    identity = start(hypervisors, root)
    reused = machines.VmIdentity(
        process=identity.process,
        pidfd_inode=identity.pidfd_inode,
        boot_ticks=identity.boot_ticks + 1,
        monitor_socket_inode=identity.monitor_socket_inode,
    )
    try:
        with pytest.raises(errors.Refusal) as raised:
            hypervisors.terminate(reused)

        assert raised.value.reason is refusals.RefusalReason.MACHINE_IDENTITY_CHANGED
        assert hypervisors.running(identity)
    finally:
        hypervisors.terminate(identity)


def test_terminating_a_machine_that_is_gone_is_refused(
    hypervisors: hypervisor_port.HypervisorPort, root: safepaths.RuntimeRoot
) -> None:
    identity = start(hypervisors, root)
    hypervisors.terminate(identity)

    with pytest.raises(errors.Refusal) as raised:
        hypervisors.terminate(identity)

    assert raised.value.reason is refusals.RefusalReason.MACHINE_NOT_RUNNING


def test_a_process_that_exits_before_its_monitor_appears_is_a_port_failure(
    hypervisors: hypervisor_port.HypervisorPort,
    root: safepaths.RuntimeRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if isinstance(hypervisors, fake_hypervisor.FakeQemu):
        hypervisors.exits_at_once = True
    else:
        monkeypatch.setenv("APEX_SHIM_EXIT", "1")

    with pytest.raises(errors.PortFailure) as raised:
        start(hypervisors, root)

    assert "qemu.log" in str(raised.value)


def test_the_monitor_socket_exists_once_spawn_answers(
    hypervisors: hypervisor_port.HypervisorPort, root: safepaths.RuntimeRoot
) -> None:
    if isinstance(hypervisors, fake_hypervisor.FakeQemu):
        pytest.skip("NOT TESTED: the fake opens no socket")
    identity = start(hypervisors, root)
    try:
        assert Path(root.child("qmp.sock").path).exists()
    finally:
        hypervisors.terminate(identity)


def test_capacity_reports_memory_space_and_the_accelerator(
    hypervisors: hypervisor_port.HypervisorPort, root: safepaths.RuntimeRoot
) -> None:
    capacity = hypervisors.capacity(root)

    assert capacity.available_memory.value > 0
    assert capacity.free_space.value > 0
    assert isinstance(capacity.kvm_accessible, bool)

"""A record reads back as the value that wrote it, and a damaged one is refused."""

from __future__ import annotations

import json

import pytest
from machinehost import RUN, Host

from apex.config import defaults
from apex.kernel import claims, commands, errors, refusals
from apex.model import machines
from apex.ports import clock
from apex.provisioning import leases


def intent(host: Host) -> leases.MachineIntent:
    return leases.MachineIntent(
        role=machines.VmRole.TEST,
        run=RUN,
        run_directory=host.run_directory,
        monitor=host.root.child("qmp.sock"),
        command=commands.Argv.of("qemu-system-x86_64", "-name", "apex-test"),
        written_at=clock.Stamp("2026-01-01T00:00:00+00:00"),
        witness=claims.EnvironmentKind.SIMULATED,
    )


def identity() -> machines.VmIdentity:
    return machines.VmIdentity(process=41, pidfd_inode=42, boot_ticks=43, monitor_socket_inode=44)


def test_an_intent_round_trips(host: Host) -> None:
    leases.write_intent(host.ports, intent(host), root=host.root)

    assert leases.read_intent(host.ports, root=host.root) == intent(host)


def test_a_lease_round_trips_and_lands_in_the_run_directory_too(host: Host) -> None:
    lease = leases.MachineLease(intent=intent(host), identity=identity())

    leases.write_lease(host.ports, lease, root=host.root)

    assert leases.read_lease(host.ports, root=host.root) == lease
    assert str(host.run_directory.path / defaults.LEASE_NAME) in host.files.writes


def test_a_released_lease_stays_readable_and_says_so(host: Host) -> None:
    lease = leases.MachineLease(intent=intent(host), identity=identity())

    leases.write_lease(host.ports, lease.release(), root=host.root)

    stored = leases.read_lease(host.ports, root=host.root)
    assert stored is not None
    assert stored.released
    assert stored.identity == identity()


def test_records_are_private(host: Host) -> None:
    leases.write_intent(host.ports, intent(host), root=host.root)

    assert host.files.mode_of(host.root.child(defaults.INTENT_NAME)) == defaults.RECORD_MODE


def test_nothing_written_reads_as_nothing(host: Host) -> None:
    assert leases.read_intent(host.ports, root=host.root) is None
    assert leases.read_lease(host.ports, root=host.root) is None


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[]",
        json.dumps({"schema": 1}).encode(),
        json.dumps({"intent": {}, "identity": {}}).encode(),
        json.dumps({"intent": {"role": "test"}, "identity": {"process": "x"}}).encode(),
    ],
)
def test_a_damaged_lease_is_refused_not_guessed(host: Host, payload: bytes) -> None:
    host.files.write_atomic(
        host.root.child(defaults.LEASE_NAME), payload, mode=defaults.RECORD_MODE
    )

    with pytest.raises(errors.Refusal) as raised:
        leases.read_lease(host.ports, root=host.root)

    assert raised.value.reason is refusals.RefusalReason.LEASE_MALFORMED


def test_an_intent_with_a_command_that_is_not_a_vector_is_refused(host: Host) -> None:
    document = dict(intent(host).document())
    document["command"] = "qemu-system-x86_64 -name apex-test"
    host.files.write_atomic(
        host.root.child(defaults.INTENT_NAME),
        json.dumps(document).encode(),
        mode=defaults.RECORD_MODE,
    )

    with pytest.raises(errors.Refusal) as raised:
        leases.read_intent(host.ports, root=host.root)

    assert raised.value.reason is refusals.RefusalReason.LEASE_MALFORMED


def test_the_witness_is_on_the_intent_and_reads_back(host: Host) -> None:
    leases.write_intent(host.ports, intent(host), root=host.root)

    stored = leases.read_intent(host.ports, root=host.root)

    assert stored is not None and stored.witness is claims.EnvironmentKind.SIMULATED
    document = intent(host).document()
    assert document["witness"] == "simulated"


def test_an_intent_without_a_witness_is_malformed(host: Host) -> None:
    document = dict(intent(host).document())
    del document["witness"]
    host.files.write_atomic(
        host.root.child(defaults.INTENT_NAME),
        json.dumps(document).encode(),
        mode=defaults.RECORD_MODE,
    )

    with pytest.raises(errors.Refusal) as raised:
        leases.read_intent(host.ports, root=host.root)

    assert raised.value.reason is refusals.RefusalReason.LEASE_MALFORMED

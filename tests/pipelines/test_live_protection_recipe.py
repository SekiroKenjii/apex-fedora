"""The live protection recipe, run end to end on fakes.

The guest answers each unit request from a table, framed under whatever token the host
chose. Every fault runs, and then the chain refuses the fake bundle: the result of a
simulated run is never recorded, which is the property the whole store rests on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from answeringguest import AnsweringGuest

from apex.adapters.fakes import fake_clock, fake_files, fake_guestshell
from apex.attestation import ledger, proofs
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import claims, identifiers, refusals, safepaths, secrets
from apex.ports import guestshell, portset
from apex.verification import recording
from apex.verification.recipes import live_protection_recipe

CANDIDATE = identifiers.Digest("c" * 64)
CHECK = identifiers.CheckId("live.disk-protection")


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "guest_ed25519").write_bytes(b"")
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def guest_target(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user="root",
        port=defaults.GUEST_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "guest_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def recorder(root: safepaths.RuntimeRoot) -> recording.Recorder:
    location = proofs.StoreLocation(root=root)
    filesystem = fake_files.MemoryFiles()
    return recording.Recorder(
        store=proofs.ProofStore(location=location, filesystem=filesystem),
        chain=ledger.Ledger(
            location=location,
            filesystem=filesystem,
            signer=ledger.ChainSigner(secrets.Secret("key")),
            clock=fake_clock.ManualClock(),
        ),
    )


def bundle(ports: portset.HostPorts, guest: fake_guestshell.ScriptedGuest) -> portset.HostPorts:
    return portset.HostPorts(
        processes=ports.processes,
        files=ports.files,
        clock=ports.clock,
        identities=ports.identities,
        locks=ports.locks,
        digests=ports.digests,
        archives=ports.archives,
        signing=ports.signing,
        downloads=ports.downloads,
        hypervisor=ports.hypervisor,
        monitor=ports.monitor,
        guest=guest,
    )


def verify(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    guest: fake_guestshell.ScriptedGuest,
    *,
    witness: claims.EnvironmentKind = claims.EnvironmentKind.VM,
) -> tuple[object, recording.Recorder]:
    held = recorder(root)
    outcome = live_protection_recipe.verify(
        bundle(ports, guest),
        guest=guest_target(root),
        wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
        candidate=CANDIDATE,
        witness=witness,
        recorder=held,
    )
    return outcome, held


def test_the_plan_delivers_the_agent_then_attempts_every_fault_then_records_once() -> None:
    assert [str(item) for item in live_protection_recipe.PLAN.order] == [
        "run.identify",
        "agent.deliver",
        "fault.live-write-denial",
        "fault.usb-write-denial",
        "attest.live.disk-protection",
    ]


def test_every_fault_runs_and_the_fake_bundle_is_refused_before_the_chain(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest(
        {
            "fault.live-write-denial": {"status": "PASS"},
            "fault.usb-write-denial": {"status": "PASS"},
        }
    )

    outcome, held = verify(ports, root, guest)

    assert not outcome.succeeded  # type: ignore[attr-defined]
    assert outcome.refusal is refusals.RefusalReason.SIMULATED_ENVIRONMENT  # type: ignore[attr-defined]
    assert outcome.attested == ()  # type: ignore[attr-defined]
    assert outcome.not_tested == (CHECK,)  # type: ignore[attr-defined]
    assert guest.asked == ["fault.live-write-denial", "fault.usb-write-denial"]
    run = outcome.facts[composition_keys.RUN_ID]  # type: ignore[attr-defined]
    assert [str(item.remote) for item in guest.sent] == [f"/var/tmp/apex-{run}/apex-agent.whl"]
    assert held.chain.head() == ledger.EMPTY
    assert held.store.absorbed == 0


def test_a_witness_the_check_cannot_accept_stops_the_run_before_any_guest_effect(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({})

    outcome, held = verify(ports, root, guest, witness=claims.EnvironmentKind.BUILD)

    assert outcome.refusal is refusals.RefusalReason.ENVIRONMENT_NOT_WITNESSED  # type: ignore[attr-defined]
    assert guest.runs == [] and guest.sent == []
    assert held.chain.head() == ledger.EMPTY


def test_a_unit_the_guest_does_not_know_is_the_guest_s_refusal(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"fault.live-write-denial": {"status": "PASS"}})

    outcome, held = verify(ports, root, guest)

    assert outcome.refusal is refusals.RefusalReason.AGENT_REFUSED  # type: ignore[attr-defined]
    assert "fault.usb-write-denial" in outcome.detail  # type: ignore[attr-defined]
    assert guest.asked == ["fault.live-write-denial", "fault.usb-write-denial"]
    assert held.chain.head() == ledger.EMPTY

"""The mint stage records one verdict per check from every report behind it.

A fake bundle can never record, so the recording path is exercised on a bundle whose fakes
declare themselves real. That declaration is exactly the lie the design says a class
attribute can tell, made here on purpose to reach the code under test and nowhere else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_digesting,
    fake_downloading,
    fake_files,
    fake_guestshell,
    fake_hypervisor,
    fake_ids,
    fake_locking,
    fake_process,
    fake_qmp,
    fake_signing,
)
from apex.attestation import ledger, minting, proofs
from apex.kernel import claims, identifiers, refusals, safepaths, secrets, verdicts
from apex.pipeline import facts, stages
from apex.ports import portset
from apex.verification import faulting, faults, recording, verifykeys
from apex.verification.stages import mint_stage

CHECK = identifiers.CheckId("live.disk-protection")
CANDIDATE = identifiers.Digest("c" * 64)
SEED = identifiers.StageId("seed")


def declared_real(cls: Any) -> Any:
    return type(f"Real{cls.__name__}", (cls,), {"environment": claims.EnvironmentKind.BUILD})


def pretending_real() -> portset.HostPorts:
    return portset.HostPorts(
        processes=declared_real(fake_process.ScriptedProcess)(),
        files=declared_real(fake_files.MemoryFiles)(),
        clock=declared_real(fake_clock.ManualClock)(),
        identities=declared_real(fake_ids.SequenceIdentities)(),
        locks=declared_real(fake_locking.MemoryLocks)(),
        digests=declared_real(fake_digesting.CountingDigests)(),
        archives=declared_real(fake_archives.MemoryArchives)(),
        signing=declared_real(fake_signing.FakeSigner)(),
        downloads=declared_real(fake_downloading.PinningFetcher)(),
        hypervisor=declared_real(fake_hypervisor.FakeQemu)(),
        monitor=declared_real(fake_qmp.ScriptedQmp)(),
        guest=declared_real(fake_guestshell.ScriptedGuest)(),
    )


@pytest.fixture
def recorder(tmp_path: Path) -> recording.Recorder:
    tmp_path.chmod(0o700)
    location = proofs.StoreLocation(root=safepaths.RuntimeRoot.adopt(tmp_path))
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


def report(name: str, status: str) -> faulting.FaultReport:
    case = faults.lookup(identifiers.ProbeId(name))
    observations = {"status": status, "scope": name}
    return faulting.report(case, observations, reply={"unit": name, "observations": observations})


def context(
    ports: portset.HostPorts,
    recorder: recording.Recorder,
    *reports: faulting.FaultReport,
    witness: claims.EnvironmentKind = claims.EnvironmentKind.VM,
) -> tuple[stages.RunContext[portset.HostPorts], list[facts.FactKey[faulting.FaultReport]]]:
    held = facts.FactMap()
    held = held.with_fact(verifykeys.WITNESS, witness, produced_by=SEED)
    held = held.with_fact(verifykeys.CANDIDATE, CANDIDATE, produced_by=SEED)
    held = held.with_fact(verifykeys.RECORDER, recorder, produced_by=SEED)
    names = []
    for item in reports:
        key = verifykeys.fault_report(item.case)
        held = held.with_fact(key, item, produced_by=SEED)
        names.append(key)
    return stages.RunContext(facts=held, ports=ports), names


def test_two_passing_reports_record_one_pass_with_both_as_proof(
    recorder: recording.Recorder,
) -> None:
    ports = pretending_real()
    run, names = context(
        ports,
        recorder,
        report("fault.live-write-denial", "PASS"),
        report("fault.usb-write-denial", "PASS"),
    )
    stage = mint_stage.for_check(CHECK, reports=names)

    result = stage.apply(run)

    assert isinstance(result, stages.Advance)
    recorded = result.facts[verifykeys.minted(CHECK)]
    assert recorded.verdict == verdicts.PASSED and recorded.sequence == 0
    assert len(recorded.proofs) == 2
    entry = recorder.chain.head()
    assert entry.sequence == 0
    assert recorder.store.absorbed == 2
    assert stage.attests == frozenset({CHECK})


def test_one_failing_report_records_a_failure(recorder: recording.Recorder) -> None:
    ports = pretending_real()
    run, names = context(
        ports,
        recorder,
        report("fault.live-write-denial", "PASS"),
        report("fault.usb-write-denial", "FAIL"),
    )

    result = mint_stage.for_check(CHECK, reports=names).apply(run)

    assert isinstance(result, stages.Advance)
    assert result.facts[verifykeys.minted(CHECK)].verdict == verdicts.FAILED


def test_the_recorded_environment_is_the_guest_s_witness_not_the_host_s(
    recorder: recording.Recorder,
) -> None:
    ports = pretending_real()
    run, names = context(ports, recorder, report("fault.live-write-denial", "PASS"))
    seen: list[claims.EnvironmentKind] = []
    original = minting.mint

    def spy(**arguments: Any) -> Any:
        seen.append(arguments["witnessed"])
        return original(**arguments)

    minting.mint = spy  # type: ignore[assignment]
    try:
        mint_stage.for_check(CHECK, reports=names).apply(run)
    finally:
        minting.mint = original  # type: ignore[assignment]

    assert seen == [claims.EnvironmentKind.VM]


def test_a_fake_bundle_is_refused_and_nothing_is_recorded(
    ports: portset.HostPorts, recorder: recording.Recorder
) -> None:
    run, names = context(ports, recorder, report("fault.live-write-denial", "PASS"))

    result = mint_stage.for_check(CHECK, reports=names).apply(run)

    assert isinstance(result, stages.Refuse)
    assert result.reason is refusals.RefusalReason.SIMULATED_ENVIRONMENT
    assert recorder.chain.head() == ledger.EMPTY
    assert recorder.store.absorbed == 0


def test_a_witness_the_check_cannot_accept_is_refused_at_preflight(
    ports: portset.HostPorts, recorder: recording.Recorder
) -> None:
    run, names = context(ports, recorder, witness=claims.EnvironmentKind.BUILD)

    verdict = mint_stage.for_check(CHECK, reports=names).preflight(run)

    assert isinstance(verdict, stages.RefuseBecause)
    assert verdict.reason is refusals.RefusalReason.ENVIRONMENT_NOT_WITNESSED

"""Every refusal the older tool made on the way in is made here, before anything is filed.

Each case violates one rule on purpose and checks two things: the refusal names the rule,
and the store and the chain are exactly as they were. The last case writes a result and
reads it back through the chain and the object store, so a record minted here is one the
fold can judge.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import fake_clock, fake_files
from apex.attestation import ledger, minting, proofs
from apex.kernel import claims, errors, identifiers, refusals, safepaths, secrets, verdicts

CANDIDATE = identifiers.Digest("c" * 64)
BUILD_CHECK = identifiers.CheckId("image.lint")
VM_CHECK = identifiers.CheckId("boot.grub-counter")
HARDWARE_CHECK = identifiers.CheckId("audio.headphones")
JSON = minting.Offered(payload=b'{"observed": true}\n', kind=".json")


@pytest.fixture
def filesystem() -> fake_files.MemoryFiles:
    return fake_files.MemoryFiles()


@pytest.fixture
def location(tmp_path: Path) -> proofs.StoreLocation:
    tmp_path.chmod(0o700)
    return proofs.StoreLocation(root=safepaths.RuntimeRoot.adopt(tmp_path))


@pytest.fixture
def store(location: proofs.StoreLocation, filesystem: fake_files.MemoryFiles) -> proofs.ProofStore:
    return proofs.ProofStore(location=location, filesystem=filesystem)


@pytest.fixture
def chain(location: proofs.StoreLocation, filesystem: fake_files.MemoryFiles) -> ledger.Ledger:
    return ledger.Ledger(
        location=location,
        filesystem=filesystem,
        signer=ledger.ChainSigner(secrets.Secret("chain key")),
        clock=fake_clock.ManualClock(),
    )


def mint(
    store: proofs.ProofStore,
    chain: ledger.Ledger,
    *,
    check: identifiers.CheckId = BUILD_CHECK,
    verdict: verdicts.Verdict = verdicts.PASSED,
    offered: tuple[minting.Offered, ...] = (JSON,),
    witnessed: claims.EnvironmentKind = claims.EnvironmentKind.BUILD,
) -> minting.Minted:
    return minting.mint(
        check=check,
        verdict=verdict,
        offered=offered,
        candidate=CANDIDATE,
        witnessed=witnessed,
        store=store,
        chain=chain,
    )


def refused(
    store: proofs.ProofStore, chain: ledger.Ledger, **arguments: object
) -> refusals.RefusalReason:
    with pytest.raises(errors.Refusal) as caught:
        mint(store, chain, **arguments)  # type: ignore[arg-type]
    assert chain.head() == ledger.EMPTY
    assert store.absorbed == 0
    return caught.value.reason


def test_a_check_outside_the_catalogue_is_refused(
    store: proofs.ProofStore, chain: ledger.Ledger
) -> None:
    reason = refused(store, chain, check=identifiers.CheckId("image.invented"))

    assert reason is refusals.RefusalReason.UNKNOWN_CHECK


def test_hardware_evidence_from_a_virtual_machine_is_refused_at_write(
    store: proofs.ProofStore, chain: ledger.Ledger
) -> None:
    reason = refused(store, chain, check=HARDWARE_CHECK, witnessed=claims.EnvironmentKind.VM)

    assert reason is refusals.RefusalReason.HARDWARE_REQUIRES_PHYSICAL


def test_a_bundle_that_witnesses_another_environment_is_refused(
    store: proofs.ProofStore, chain: ledger.Ledger
) -> None:
    reason = refused(store, chain, check=VM_CHECK, witnessed=claims.EnvironmentKind.BUILD)

    assert reason is refusals.RefusalReason.ENVIRONMENT_NOT_WITNESSED


def test_a_simulated_bundle_is_refused_whatever_the_check(
    store: proofs.ProofStore, chain: ledger.Ledger
) -> None:
    reason = refused(store, chain, witnessed=claims.EnvironmentKind.SIMULATED)

    assert reason is refusals.RefusalReason.SIMULATED_ENVIRONMENT


def test_a_proof_kind_the_check_does_not_accept_is_refused(
    store: proofs.ProofStore, chain: ledger.Ledger
) -> None:
    """boot.grub-counter accepts only JSON; a screenshot is a permitted kind, but not here."""
    screenshot = minting.Offered(payload=b"P6 1 1 255\n\0\0\0", kind=".ppm")

    reason = refused(
        store,
        chain,
        check=VM_CHECK,
        offered=(JSON, screenshot),
        witnessed=claims.EnvironmentKind.VM,
    )

    assert reason is refusals.RefusalReason.PROOF_KIND_NOT_ACCEPTED


def test_a_biometric_template_is_never_a_permitted_kind(
    store: proofs.ProofStore, chain: ledger.Ledger
) -> None:
    template = minting.Offered(payload=b"\x00fingerprint", kind=".fpt")

    reason = refused(store, chain, offered=(template,))

    assert reason is refusals.RefusalReason.PROOF_KIND_NOT_ACCEPTED


def test_a_pass_without_proof_is_refused(store: proofs.ProofStore, chain: ledger.Ledger) -> None:
    reason = refused(store, chain, offered=())

    assert reason is refusals.RefusalReason.PASS_REQUIRES_PROOF


def test_a_failure_may_be_recorded_without_proof(
    store: proofs.ProofStore, chain: ledger.Ledger
) -> None:
    minted = mint(store, chain, verdict=verdicts.FAILED, offered=())

    assert minted.sealed.entry.event.verdict == verdicts.FAILED
    assert minted.proofs == ()
    assert chain.head().sequence == 0


def test_an_empty_proof_is_refused_before_anything_is_filed(
    store: proofs.ProofStore, chain: ledger.Ledger
) -> None:
    reason = refused(store, chain, offered=(JSON, minting.Offered(payload=b"", kind=".log")))

    assert reason is refusals.RefusalReason.PROOF_IS_EMPTY


def test_a_minted_result_is_readable_from_the_chain_and_the_objects(
    store: proofs.ProofStore,
    chain: ledger.Ledger,
    filesystem: fake_files.MemoryFiles,
    location: proofs.StoreLocation,
) -> None:
    log = minting.Offered(payload=b"lint: clean\n", kind=".log")

    minted = mint(store, chain, offered=(JSON, log))

    body = filesystem.read_bytes(location.chain_path(), limit=1_000_000)
    lines = [line for line in body.split(b"\n") if line]
    report = ledger.replay(
        lines, signer=ledger.ChainSigner(secrets.Secret("chain key")), head=chain.head()
    )
    assert report.intact and report.entries == 1
    event = minted.sealed.entry.event
    assert event.kind is ledger.EntryKind.RECORDED
    assert event.check == BUILD_CHECK
    assert event.candidate == CANDIDATE
    assert event.environment is claims.EnvironmentKind.BUILD
    assert [store.load(proof) for proof in minted.proofs] == [JSON.payload, log.payload]
    assert event.proofs == tuple(proof.digest for proof in minted.proofs)


def test_the_same_bytes_offered_twice_are_filed_once(
    store: proofs.ProofStore, chain: ledger.Ledger
) -> None:
    minted = mint(store, chain, offered=(JSON, JSON))

    assert store.absorbed == 1
    assert len(minted.proofs) == 2
    assert minted.proofs[0].digest == minted.proofs[1].digest


def test_the_witnessed_environment_is_what_the_entry_records(
    store: proofs.ProofStore, chain: ledger.Ledger
) -> None:
    minted = mint(store, chain, check=VM_CHECK, witnessed=claims.EnvironmentKind.VM)

    assert minted.sealed.entry.event.environment is claims.EnvironmentKind.VM
    assert minted.check == VM_CHECK

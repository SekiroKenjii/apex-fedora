"""A proof is addressed by what it contains, so it cannot be swapped under a record.

The store the old code uses names a proof by a path chosen at record time. Anyone who can
write that path can change what a passing record cites without changing the record. Here the
name is the digest, so altering the bytes moves the object and the citation stops resolving.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import fake_files
from apex.attestation import proofs
from apex.kernel import errors, quantities, refusals, safepaths

SCREENSHOT = b"\x89PNG\r\n\x1a\n a captured frame"
REPORT = b'{"unit": "greenboot", "state": "active"}'


@pytest.fixture
def location(tmp_path: Path) -> proofs.StoreLocation:
    tmp_path.chmod(0o700)
    return proofs.StoreLocation(root=safepaths.RuntimeRoot.adopt(tmp_path))


@pytest.fixture
def store(location: proofs.StoreLocation) -> proofs.ProofStore:
    return proofs.ProofStore(location=location, filesystem=fake_files.MemoryFiles())


def test_the_address_is_derived_from_the_content(store: proofs.ProofStore) -> None:
    first = store.absorb(SCREENSHOT, kind=".png")
    second = store.absorb(SCREENSHOT, kind=".png")

    assert first.digest == second.digest
    assert store.absorbed == 1


def test_a_proof_shared_by_three_checks_is_stored_once(store: proofs.ProofStore) -> None:
    for _ in range(3):
        store.absorb(REPORT, kind=".json")

    assert store.absorbed == 1


def test_different_content_lands_at_a_different_address(store: proofs.ProofStore) -> None:
    png = store.absorb(SCREENSHOT, kind=".png")
    report = store.absorb(REPORT, kind=".json")

    assert png.digest != report.digest
    assert store.absorbed == 2


def test_the_object_path_fans_out_on_the_first_two_characters(
    location: proofs.StoreLocation,
) -> None:
    digest = proofs.address(SCREENSHOT)

    target = location.object_path(digest)

    assert target.path.parent.name == digest.hex[: proofs.FAN_OUT]
    assert target.path.name == digest.hex


def test_every_object_is_written_private(location: proofs.StoreLocation) -> None:
    filesystem = fake_files.MemoryFiles()
    store = proofs.ProofStore(location=location, filesystem=filesystem)

    proof = store.absorb(SCREENSHOT, kind=".png")

    assert filesystem.mode_of(location.object_path(proof.digest)) == quantities.FileMode(0o600)


def test_a_biometric_template_is_not_a_proof(store: proofs.ProofStore) -> None:
    with pytest.raises(errors.Refusal) as raised:
        store.absorb(b"minutiae", kind=".fpt")

    assert raised.value.reason is refusals.RefusalReason.PROOF_KIND_NOT_ACCEPTED


def test_loading_verifies_the_bytes_it_returns(store: proofs.ProofStore) -> None:
    proof = store.absorb(REPORT, kind=".json")

    assert store.load(proof) == REPORT


def test_an_altered_object_is_refused_on_load(location: proofs.StoreLocation) -> None:
    filesystem = fake_files.MemoryFiles()
    store = proofs.ProofStore(location=location, filesystem=filesystem)
    proof = store.absorb(REPORT, kind=".json")

    filesystem.write_atomic(
        location.object_path(proof.digest),
        b'{"unit": "greenboot", "state": "failed"}',
        mode=quantities.FileMode(0o600),
    )

    with pytest.raises(errors.Refusal) as raised:
        store.load(proof)
    assert raised.value.reason is refusals.RefusalReason.PROOF_ALTERED


def test_an_object_that_grew_cannot_exhaust_memory(location: proofs.StoreLocation) -> None:
    filesystem = fake_files.MemoryFiles()
    store = proofs.ProofStore(location=location, filesystem=filesystem)
    proof = store.absorb(REPORT, kind=".json")

    filesystem.write_atomic(
        location.object_path(proof.digest),
        REPORT + b"x" * 4096,
        mode=quantities.FileMode(0o600),
    )

    with pytest.raises(errors.Refusal) as raised:
        store.load(proof)
    assert raised.value.reason is refusals.RefusalReason.PROOF_ALTERED


def test_the_store_refuses_to_live_inside_the_legacy_directory(tmp_path: Path) -> None:
    tmp_path.chmod(0o700)

    with pytest.raises(errors.Refusal) as raised:
        proofs.StoreLocation(
            root=safepaths.RuntimeRoot.adopt(tmp_path), area=proofs.LEGACY_AREA
        )

    assert raised.value.reason is refusals.RefusalReason.STORE_AREA_NOT_PERMITTED


def test_a_missing_object_is_reported_rather_than_raised(store: proofs.ProofStore) -> None:
    absent = proofs.Proof(digest=proofs.address(b"never absorbed"), kind=".txt", byte_count=14)

    assert not store.holds(absent)


def test_an_absorbed_object_is_held(store: proofs.ProofStore) -> None:
    assert store.holds(store.absorb(SCREENSHOT, kind=".png"))

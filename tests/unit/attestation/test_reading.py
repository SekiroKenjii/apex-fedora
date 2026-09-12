"""Reading a v1 store: every record marked, every damaged one named, nothing written.

Four behaviours here are regressions the design review measured against the code as committed.
A single unreadable document used to blind the whole store, a symlinked one used to vanish, a
malformed proof entry used to escape as a bare key error, and a store with no candidate used to
report eighteen passes where the code it replaces refuses every record as unbound.
"""

from __future__ import annotations

import json
from pathlib import Path

from apex.adapters.real import real_files
from apex.attestation import attesting, ledger, reading
from apex.kernel import refusals

DIGEST = "sha256:" + "c" * 64
CANDIDATE = {"digest": DIGEST, "build_id": "ee97157d34b9480186730786268f6a0c"}


def record(
    check: str, status: str = "PASS", *, proofs: list[dict[str, str]] | None = None
) -> dict[str, object]:
    return {
        "check": check,
        "digest": DIGEST,
        "status": status,
        "environment": {"kind": "build", "description": "a build host"},
        "recorded_at": "2026-01-01T00:00:00+00:00",
        "reason": "",
        "proof": proofs if proofs is not None else [],
    }


def store(root: Path, *, candidate: bool = True) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "evidence").mkdir(exist_ok=True)
    if candidate:
        (root / "candidate.json").write_text(json.dumps(CANDIDATE))
    return root


def put(root: Path, name: str, document: object) -> Path:
    target = root / "evidence" / f"{name}.json"
    target.write_text(json.dumps(document) if not isinstance(document, str) else document)
    return target


def inventory(root: Path) -> set[tuple[str, int, int]]:
    return {
        (str(item.relative_to(root)), item.stat().st_mode, item.stat().st_size)
        for item in root.rglob("*")
    }


def test_every_record_from_a_v1_store_is_imported_and_carries_both_permanent_limits(
    tmp_path: Path,
) -> None:
    root = store(tmp_path)
    put(root, "one", record("build.one"))
    put(root, "two", record("build.two", "FAIL"))

    found = reading.read_store(root, files=real_files.LocalFiles())

    assert found.version == 1
    assert len(found.attestations) == 2
    for entry in found.attestations:
        assert entry.kind is ledger.EntryKind.IMPORTED
        assert entry.resolved.imported
        assert entry.limits >= attesting.LEGACY_LIMITS


def test_one_unreadable_record_becomes_a_fault_and_the_others_still_resolve(
    tmp_path: Path,
) -> None:
    root = store(tmp_path)
    put(root, "one", record("build.one"))
    put(root, "damaged", "{ not json")
    put(root, "two", record("build.two"))

    found = reading.read_store(root, files=real_files.LocalFiles())

    assert {entry.check for entry in found.attestations} == {"build.one", "build.two"}
    assert any("damaged.json" in fault for fault in found.faults)


def test_a_symlinked_record_becomes_a_fault_rather_than_a_silent_absence(
    tmp_path: Path,
) -> None:
    root = store(tmp_path)
    real = put(root, "one", record("build.one"))
    (root / "evidence" / "linked.json").symlink_to(real)

    found = reading.read_store(root, files=real_files.LocalFiles())

    assert len(found.attestations) == 1
    assert any(
        fault.startswith(refusals.RefusalReason.PATH_IS_A_SYMLINK.value)
        for fault in found.faults
    )


def test_a_malformed_proof_entry_is_a_named_fault_not_a_key_error(tmp_path: Path) -> None:
    root = store(tmp_path)
    put(root, "one", record("build.one", proofs=[{"path": "a.txt"}]))

    found = reading.read_store(root, files=real_files.LocalFiles())

    assert found.attestations == ()
    assert any(
        fault.startswith(refusals.RefusalReason.MALFORMED_PROOF_REFERENCE.value)
        for fault in found.faults
    )


def test_a_store_with_no_candidate_drops_every_record_and_says_so(tmp_path: Path) -> None:
    """The code this replaces refuses every record as unbound; the fold alone would not."""
    root = store(tmp_path, candidate=False)
    put(root, "one", record("build.one"))
    put(root, "two", record("build.two"))

    found = reading.read_store(root, files=real_files.LocalFiles())

    assert found.candidate is None
    assert found.attestations == ()
    assert len(found.faults) == 2
    for fault in found.faults:
        assert fault.startswith(refusals.RefusalReason.STALE_EVIDENCE.value)


def test_the_reading_never_opens_history_or_candidate_history(tmp_path: Path) -> None:
    root = store(tmp_path)
    put(root, "one", record("build.one"))
    history = root / "evidence" / "history"
    history.mkdir()
    (history / "old.json").write_text(json.dumps(record("build.rotated")))
    archive = root / "candidate-history" / "abc" / "evidence"
    archive.mkdir(parents=True)
    (archive / "old.json").write_text(json.dumps(record("build.archived")))

    found = reading.read_store(root, files=real_files.LocalFiles())

    assert {entry.check for entry in found.attestations} == {"build.one"}


def test_reading_a_store_writes_nothing_and_creates_nothing_under_its_root(
    tmp_path: Path,
) -> None:
    root = store(tmp_path)
    put(root, "one", record("build.one"))
    before = inventory(root)

    reading.read_store(root, files=real_files.LocalFiles())

    assert inventory(root) == before


def test_an_empty_store_reads_as_version_one_with_nothing_in_it(tmp_path: Path) -> None:
    found = reading.read_store(store(tmp_path), files=real_files.LocalFiles())

    assert found.version == 1
    assert found.attestations == ()
    assert found.faults == ()

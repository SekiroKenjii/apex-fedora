"""Read the stored v1 documents without moving or rewriting a byte of them.

The parser is exercised against the same synthetic root the command corpus uses, so a shape
that exists on disk today is a shape this reads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.kernel import claims, errors, identifiers, refusals, verdicts
from apex.model import runtimestate
from migration import synthetic_root


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return synthetic_root.build(tmp_path / "runtime")


def test_the_candidate_document_parses(root: Path) -> None:
    candidate = runtimestate.read_candidate(root / "candidate.json")

    assert str(candidate.digest) == synthetic_root.DIGEST
    assert str(candidate.build) == synthetic_root.BUILD_ID


def test_a_candidate_without_a_full_manifest_digest_is_refused(tmp_path: Path) -> None:
    document = tmp_path / "candidate.json"
    document.write_text('{"digest": "sha256:short", "build_id": "' + "0" * 32 + '"}')

    with pytest.raises(errors.Refusal) as raised:
        runtimestate.read_candidate(document)

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_DIGEST


def test_every_stored_evidence_record_parses(root: Path) -> None:
    records = runtimestate.read_evidence_directory(root / "evidence")

    assert len(records) == len(synthetic_root.RECORDS)


def test_a_passing_record_keeps_its_proof_references(root: Path) -> None:
    stored = runtimestate.read_evidence_directory(root / "evidence")
    records = {str(item.check): item for item in stored}
    record = records["boot.ten-cycles"]

    assert record.verdict == verdicts.PASSED
    assert len(record.proofs) == 2
    assert record.proofs[0].relative_path.startswith(synthetic_root.RECORDS[0].capture or "")


def test_a_blocked_record_carries_no_proof(root: Path) -> None:
    stored = runtimestate.read_evidence_directory(root / "evidence")
    records = {str(item.check): item for item in stored}

    assert records["audio.speakers"].verdict == verdicts.BLOCKED
    assert records["audio.speakers"].proofs == ()


def test_a_hardware_record_reports_a_physical_environment(root: Path) -> None:
    stored = runtimestate.read_evidence_directory(root / "evidence")
    records = {str(item.check): item for item in stored}

    assert records["audio.speakers"].environment is claims.EnvironmentKind.PHYSICAL


def test_an_unknown_status_is_refused(tmp_path: Path) -> None:
    document = tmp_path / "x.json"
    document.write_text(
        '{"check": "boot.ten-cycles", "digest": "sha256:'
        + "a" * 64
        + '", "status": "MAYBE", "environment": {"kind": "vm", "description": "d"},'
        ' "recorded_at": "2026-01-01T00:00:00+00:00", "reason": "", "proof": []}'
    )

    with pytest.raises(errors.Refusal) as raised:
        runtimestate.read_evidence_record(document)

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_VERDICT


def test_an_unknown_environment_kind_is_refused(tmp_path: Path) -> None:
    document = tmp_path / "x.json"
    document.write_text(
        '{"check": "boot.ten-cycles", "digest": "sha256:'
        + "a" * 64
        + '", "status": "PASS", "environment": {"kind": "wishful", "description": "d"},'
        ' "recorded_at": "2026-01-01T00:00:00+00:00", "reason": "", "proof": []}'
    )

    with pytest.raises(errors.Refusal):
        runtimestate.read_evidence_record(document)


def test_the_superseded_history_parses(root: Path) -> None:
    history = runtimestate.read_evidence_directory(root / "evidence" / "history")

    assert len(history) == 1
    assert history[0].verdict == verdicts.FAILED


def test_an_archived_candidate_parses(root: Path) -> None:
    archives = runtimestate.read_candidate_history(root / "candidate-history")

    assert len(archives) == 1
    assert str(archives[0].candidate.digest) == synthetic_root.SUPERSEDED_DIGEST


def test_reading_never_writes(root: Path) -> None:
    before = {path: path.stat().st_mtime_ns for path in sorted(root.rglob("*")) if path.is_file()}

    runtimestate.read_candidate(root / "candidate.json")
    runtimestate.read_evidence_directory(root / "evidence")
    runtimestate.read_candidate_history(root / "candidate-history")

    after = {path: path.stat().st_mtime_ns for path in sorted(root.rglob("*")) if path.is_file()}
    assert before == after


def test_a_record_reports_the_check_it_belongs_to(root: Path) -> None:
    records = runtimestate.read_evidence_directory(root / "evidence")

    for record in records:
        assert isinstance(record.check, identifiers.CheckId)


def test_an_absent_directory_yields_nothing(tmp_path: Path) -> None:
    assert runtimestate.read_evidence_directory(tmp_path / "absent") == ()

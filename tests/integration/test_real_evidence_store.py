"""Read the operator's real evidence store. Opt-in, and strictly read only."""

from __future__ import annotations

import collections
import json
import os
from pathlib import Path

import pytest

from apex.adapters.real import real_files
from apex.attestation import (
    attesting,
    ledger,
    readiness,
    reading,
    resolving,
    retracting,
)
from apex.model import runtimestate, storemark

pytestmark = pytest.mark.integration

FROZEN_PASSED = 18
FROZEN_BLOCKED = 6
FROZEN_NOT_TESTED = 38


def runtime_root() -> Path:
    raw = os.environ.get("APEX_STATE_DIR", "~/.local/share/apex-fedora/runtime")
    return Path(raw).expanduser()


@pytest.fixture
def root() -> Path:
    candidate = runtime_root()
    if not (candidate / "candidate.json").is_file():
        pytest.skip("NOT TESTED: no real runtime root on this machine")
    return candidate


def test_the_real_candidate_parses(root: Path) -> None:
    assert runtimestate.read_candidate(root / "candidate.json").digest


def test_every_real_evidence_record_parses(root: Path) -> None:
    records = runtimestate.read_evidence_directory(root / "evidence")

    assert len(records) == FROZEN_PASSED + FROZEN_BLOCKED


def test_the_verdict_tally_matches_the_recorded_readiness(root: Path) -> None:
    records = runtimestate.read_evidence_directory(root / "evidence")
    tally = collections.Counter(record.verdict.stored_name for record in records)

    assert tally["PASS"] == FROZEN_PASSED
    assert tally["BLOCKED"] == FROZEN_BLOCKED


def test_the_untested_remainder_is_the_catalogue_minus_the_records(root: Path) -> None:
    catalogue = json.loads(Path("config/checks.json").read_text())
    total = sum(len(names) for names in catalogue.values())
    records = runtimestate.read_evidence_directory(root / "evidence")

    assert total - len(records) == FROZEN_NOT_TESTED


def test_every_archived_candidate_parses(root: Path) -> None:
    for archive in runtimestate.read_candidate_history(root / "candidate-history"):
        assert archive.candidate.digest
        assert archive.records


def test_reading_the_real_store_changes_nothing(root: Path) -> None:
    watched = sorted((root / "evidence").rglob("*.json"))
    before = {path: path.stat().st_mtime_ns for path in watched}

    runtimestate.read_evidence_directory(root / "evidence")
    runtimestate.read_candidate_history(root / "candidate-history")

    assert {path: path.stat().st_mtime_ns for path in watched} == before


def test_the_real_store_reads_as_version_one_because_it_carries_no_mark(root: Path) -> None:
    assert storemark.read_mark(root) == storemark.Unmarked()
    found = reading.read_store(root, files=real_files.LocalFiles())
    assert found.version == storemark.FIRST_VERSION


def test_the_versioned_reading_of_the_real_store_still_folds_to_the_frozen_tally(
    root: Path,
) -> None:
    """Acceptance criterion ten, checked on the real data rather than argued."""
    found = reading.read_store(root, files=real_files.LocalFiles())
    outcome = readiness.evaluate(
        required=resolving.required_environments(),
        records=found.records,
        candidate=found.candidate,
    )

    assert found.faults == ()
    assert outcome.counts["PASS"] == FROZEN_PASSED
    assert outcome.counts["BLOCKED"] == FROZEN_BLOCKED
    assert outcome.counts["NOT TESTED"] == FROZEN_NOT_TESTED
    assert not outcome.ready


def test_every_record_from_the_real_store_is_imported_with_both_permanent_limits(
    root: Path,
) -> None:
    """The only mechanical check that the import was actually applied."""
    found = reading.read_store(root, files=real_files.LocalFiles())

    assert found.attestations
    for entry in found.attestations:
        assert entry.kind is ledger.EntryKind.IMPORTED
        assert entry.resolved.imported
        assert entry.limits >= attesting.LEGACY_LIMITS


def test_strict_readiness_withholds_every_pass_and_keeps_every_finding(root: Path) -> None:
    found = reading.read_store(root, files=real_files.LocalFiles())
    outcome = readiness.evaluate(
        required=resolving.required_environments(),
        records=found.records,
        candidate=found.candidate,
    )
    strict, withheld = retracting.retract(outcome, attestations=found.attestations)

    assert len(withheld) == FROZEN_PASSED
    assert strict.counts["BLOCKED"] == FROZEN_BLOCKED
    assert strict.counts["NOT TESTED"] == FROZEN_NOT_TESTED + FROZEN_PASSED
    assert "PASS" not in strict.counts
    assert not strict.ready

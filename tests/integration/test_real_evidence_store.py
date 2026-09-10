"""Read the operator's real evidence store. Opt-in, and strictly read only."""

from __future__ import annotations

import collections
import json
import os
from pathlib import Path

import pytest

from apex.model import runtimestate

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

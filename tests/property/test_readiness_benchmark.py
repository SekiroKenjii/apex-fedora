"""Readiness over ten thousand chain entries and five hundred proofs stays under two seconds.

The specification's table names the threshold and the memory ceiling. The store is built
in memory through the same recorder every run uses, read back through the versioned reader
and folded; only the reading and the fold are timed, since building the store is the work
of ten thousand earlier runs.
"""

from __future__ import annotations

import time
import tracemalloc
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_clock, fake_files, fake_ids
from apex.attestation import catalogue, minting, readiness, resolving
from apex.kernel import claims, identifiers, safepaths, verdicts
from apex.model import storemark
from apex.verification import recording

ENTRIES = 10_000
PROOFS = 500
SECONDS = 2.0
MEBIBYTES = 100
CANDIDATE = identifiers.Digest("d" * 64)

pytestmark = pytest.mark.benchmark


def filled_store(root: safepaths.RuntimeRoot) -> fake_files.MemoryFiles:
    files = fake_files.MemoryFiles()
    recorder = recording.Recorder.open(
        root, filesystem=files, identities=fake_ids.SequenceIdentities(),
        clock=fake_clock.ManualClock(),
    )
    specs = list(catalogue.sealed().values())
    for index in range(ENTRIES):
        spec = specs[index % len(specs)]
        payload = b"proof %d" % (index % PROOFS)
        recorder.record(
            check=spec.id,
            verdict=verdicts.PASSED,
            offered=[minting.Offered(payload=payload, kind=spec.accepted_proof_kinds[0])],
            candidate=CANDIDATE,
            witnessed=spec.environment,
        )
    return files


def test_reading_and_folding_ten_thousand_entries_stays_within_the_thresholds(
    tmp_path: Path,
) -> None:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    root = safepaths.RuntimeRoot.adopt(base)
    files = filled_store(root)
    (base / storemark.MARK_NAME).write_bytes(storemark.document(storemark.SECOND_VERSION))
    required = resolving.required_environments()

    tracemalloc.start()
    started = time.perf_counter()
    records, candidate = resolving.resolve_store(base, files=files)
    outcome = readiness.evaluate(required=required, records=records, candidate=candidate)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(records) == len(required)
    assert outcome.counts.get("PASS") == len(required)
    assert not outcome.faults
    assert elapsed < SECONDS, f"{elapsed:.2f}s for {ENTRIES} entries"
    assert peak < MEBIBYTES * 1024 * 1024, f"{peak / 1024 / 1024:.1f} MiB at peak"
    assert files.appended == ENTRIES


def test_the_chain_environment_is_the_check_s_not_a_simulation() -> None:
    spec = next(iter(catalogue.sealed().values()))

    assert spec.environment is not claims.EnvironmentKind.SIMULATED

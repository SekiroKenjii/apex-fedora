"""Reading a version two store: the chain counts, the legacy documents stay imported.

Everything is written the way the product writes it, through the minting path on the real
file adapter, and then read back through the elected reader. The awkward shapes are the
chain's: an altered object, an edited line, a key that is gone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.adapters.real import real_clock, real_files, real_ids
from apex.attestation import ledger, minting, readiness, reading, resolving
from apex.kernel import claims, identifiers, safepaths, verdicts
from apex.model import storemark
from apex.verification import recording

DIGEST = identifiers.Digest("c" * 64)
BUILD_CHECK = identifiers.CheckId("image.lint")
OTHER_BUILD_CHECK = identifiers.CheckId("fingerprint.virtual-cleanup")
LEGACY = {
    "check": "image.lint",
    "digest": str(DIGEST),
    "status": "FAIL",
    "environment": {"kind": "build", "description": "a build host"},
    "recorded_at": "2026-01-01T00:00:00+00:00",
    "reason": "",
    "proof": [],
}


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "candidate.json").write_text(
        json.dumps({"digest": str(DIGEST), "build_id": "ee97157d34b9480186730786268f6a0c"})
    )
    (base / "evidence").mkdir()
    (base / "evidence" / "image.lint.json").write_text(json.dumps(LEGACY))
    return safepaths.RuntimeRoot.adopt(base)


def opened(root: safepaths.RuntimeRoot) -> recording.Recorder:
    return recording.Recorder.open(
        root,
        filesystem=real_files.LocalFiles(),
        identities=real_ids.RandomIdentities(),
        clock=real_clock.SystemClock(),
    )


def mint(
    recorder: recording.Recorder,
    check: identifiers.CheckId = BUILD_CHECK,
    verdict: verdicts.Verdict = verdicts.PASSED,
    payload: bytes = b'{"lint": "clean"}\n',
) -> minting.Minted:
    return minting.mint(
        check=check,
        verdict=verdict,
        offered=[minting.Offered(payload=payload, kind=".json")],
        candidate=DIGEST,
        witnessed=claims.EnvironmentKind.BUILD,
        store=recorder.store,
        chain=recorder.chain,
    )


def read(root: safepaths.RuntimeRoot) -> readiness.Outcome:
    records, candidate = resolving.resolve_store(root.path, files=real_files.LocalFiles())
    return readiness.evaluate(
        required=resolving.required_environments(), records=records, candidate=candidate
    )


def test_an_unopened_root_is_still_read_as_version_one(root: safepaths.RuntimeRoot) -> None:
    found = reading.read_store(root.path, files=real_files.LocalFiles())

    assert found.version == 1
    assert [item.check for item in found.attestations] == ["image.lint"]
    assert found.attestations[0].kind is ledger.EntryKind.IMPORTED


def test_opening_marks_the_root_and_lays_down_one_key(root: safepaths.RuntimeRoot) -> None:
    first = opened(root)
    minted = mint(first)
    second = opened(root)

    assert storemark.read_mark(root.path) == storemark.Marked(2)
    key = root.path / "attestation" / "ledger" / "key"
    assert key.is_file() and (key.stat().st_mode & 0o777) == 0o600
    assert len(key.read_text()) == 64
    link = ledger.link_after(ledger.GENESIS, minted.sealed.entry)
    assert second.chain.head().link == first.chain.head().link == link
    assert mint(second).sealed.entry.sequence == 1


def test_a_recorded_entry_supersedes_the_imported_document_for_its_check(
    root: safepaths.RuntimeRoot,
) -> None:
    mint(opened(root))

    found = reading.read_store(root.path, files=real_files.LocalFiles())
    outcome = read(root)

    assert found.version == 2
    (item,) = [item for item in found.attestations if item.check == "image.lint"]
    assert item.kind is ledger.EntryKind.RECORDED
    assert item.limits == frozenset()
    assert item.origin == "chain#0"
    assert item.resolved.proofs_intact and item.resolved.proof_count == 1
    assert outcome.verdicts["image.lint"] == verdicts.PASSED
    assert outcome.faults == ()


def test_the_latest_entry_for_a_check_is_the_one_that_counts(root: safepaths.RuntimeRoot) -> None:
    recorder = opened(root)
    mint(recorder)
    mint(recorder, verdict=verdicts.FAILED, payload=b'{"lint": "dirty"}\n')

    found = reading.read_store(root.path, files=real_files.LocalFiles())

    (item,) = [item for item in found.attestations if item.check == "image.lint"]
    assert item.origin == "chain#1"
    assert item.resolved.verdict == verdicts.FAILED


def test_an_altered_object_blocks_the_check_it_proved(root: safepaths.RuntimeRoot) -> None:
    minted = mint(opened(root))
    target = root.path / "attestation" / "objects" / minted.proofs[0].digest.hex[:2]
    (target / minted.proofs[0].digest.hex).write_bytes(b'{"lint": "edited"}\n')

    outcome = read(root)

    assert outcome.verdicts["image.lint"] == verdicts.BLOCKED
    assert any("proof-altered" in fault for fault in outcome.faults)


def test_an_edited_line_breaks_the_chain_there_and_keeps_what_came_before(
    root: safepaths.RuntimeRoot,
) -> None:
    recorder = opened(root)
    mint(recorder)
    mint(recorder, check=OTHER_BUILD_CHECK)
    chain = root.path / "attestation" / "ledger" / "chain.jsonl"
    lines = chain.read_bytes().splitlines()
    second = json.loads(lines[1])
    second["entry"]["verdict"] = "FAIL"
    lines[1] = json.dumps(second).encode()
    chain.write_bytes(b"\n".join(lines) + b"\n")

    found = reading.read_store(root.path, files=real_files.LocalFiles())

    assert [item.check for item in found.attestations] == ["image.lint"]
    assert found.attestations[0].kind is ledger.EntryKind.RECORDED
    assert any("breaks at sequence 1" in fault for fault in found.faults)


def test_a_chain_without_its_key_counts_nothing_and_says_so(root: safepaths.RuntimeRoot) -> None:
    mint(opened(root))
    (root.path / "attestation" / "ledger" / "key").unlink()

    found = reading.read_store(root.path, files=real_files.LocalFiles())

    assert [item.kind for item in found.attestations] == [ledger.EntryKind.IMPORTED]
    assert any("no key" in fault for fault in found.faults)


def test_a_marked_root_with_no_chain_yet_reads_only_the_imported_documents(
    root: safepaths.RuntimeRoot,
) -> None:
    opened(root)

    found = reading.read_store(root.path, files=real_files.LocalFiles())

    assert found.version == 2
    assert [item.kind for item in found.attestations] == [ledger.EntryKind.IMPORTED]
    assert found.faults == ()


def test_a_root_marked_with_a_later_version_is_refused_for_writing(
    root: safepaths.RuntimeRoot,
) -> None:
    (root.path / "schema.json").write_text(json.dumps({"schema": 3}))

    with pytest.raises(Exception, match="store-version-not-supported"):
        opened(root)

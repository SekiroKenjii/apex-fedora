"""The ledger only grows, and every entry commits to the one before it.

Today a result is a file in a directory. Deleting the file lowers the readiness answer and
leaves nothing behind that says so. Here removing or editing an entry breaks the chain at a
sequence the report can name.

The message authentication code detects an edit made without the key. The key sits beside the
chain under the same account, so this is protection against accident and against a reader
who cannot write, not against the operator of the machine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_files, fake_wallclock
from apex.attestation import ledger, proofs
from apex.kernel import claims, errors, identifiers, refusals, safepaths, secrets, verdicts

CANDIDATE = identifiers.Digest("c" * 64)
PROOF = identifiers.Digest("d" * 64)


def signer(material: str = "chain key") -> ledger.ChainSigner:
    return ledger.ChainSigner(secrets.Secret(material))


def event(
    check: str,
    verdict: verdicts.Verdict = verdicts.PASSED,
    *,
    environment: claims.EnvironmentKind = claims.EnvironmentKind.BUILD,
) -> ledger.Event:
    return ledger.Event(
        kind=ledger.EntryKind.RECORDED,
        check=identifiers.CheckId(check),
        verdict=verdict,
        environment=environment,
        candidate=CANDIDATE,
        proofs=(PROOF,),
        scope_limits=(),
    )


@pytest.fixture
def location(tmp_path: Path) -> proofs.StoreLocation:
    tmp_path.chmod(0o700)
    return proofs.StoreLocation(root=safepaths.RuntimeRoot.adopt(tmp_path))


@pytest.fixture
def filesystem() -> fake_files.MemoryFiles:
    return fake_files.MemoryFiles()


@pytest.fixture
def chain(
    location: proofs.StoreLocation, filesystem: fake_files.MemoryFiles
) -> ledger.Ledger:
    return ledger.Ledger(
        location=location,
        filesystem=filesystem,
        signer=signer(),
        wallclock=fake_wallclock.FixedWallClock(),
    )


def lines_of(filesystem: fake_files.MemoryFiles, location: proofs.StoreLocation) -> list[bytes]:
    body = filesystem.read_bytes(location.chain_path(), limit=1_000_000)
    return [line for line in body.split(b"\n") if line]


def test_the_first_link_commits_to_the_genesis_value(chain: ledger.Ledger) -> None:
    sealed = chain.append(event("build.one"))

    assert sealed.entry.sequence == 0
    assert sealed.link == ledger.link_after(ledger.GENESIS, sealed.entry)


def test_each_link_commits_to_the_one_before_it(chain: ledger.Ledger) -> None:
    first = chain.append(event("build.one"))
    second = chain.append(event("build.two"))

    assert second.entry.sequence == 1
    assert second.link == ledger.link_after(first.link, second.entry)


def test_a_replayed_chain_is_intact(
    chain: ledger.Ledger, filesystem: fake_files.MemoryFiles, location: proofs.StoreLocation
) -> None:
    chain.append(event("build.one"))
    chain.append(event("build.two"))

    report = ledger.replay(lines_of(filesystem, location), signer=signer(), head=chain.head())

    assert report.intact
    assert report.entries == 2
    assert report.first_break is None


def test_an_edited_entry_is_named_by_its_sequence(
    chain: ledger.Ledger, filesystem: fake_files.MemoryFiles, location: proofs.StoreLocation
) -> None:
    chain.append(event("build.one"))
    chain.append(event("build.two", verdicts.FAILED))
    chain.append(event("build.three"))
    lines = lines_of(filesystem, location)

    document = json.loads(lines[1])
    document["entry"]["verdict"] = verdicts.Passed.stored_name
    lines[1] = json.dumps(document).encode()

    report = ledger.replay(lines, signer=signer(), head=chain.head())

    assert not report.intact
    assert report.first_break is not None
    assert report.first_break.sequence == 1
    assert report.first_break.cause is ledger.Break.LINK_MISMATCH


def test_recomputing_the_link_still_needs_the_key(
    chain: ledger.Ledger, filesystem: fake_files.MemoryFiles, location: proofs.StoreLocation
) -> None:
    chain.append(event("build.one"))
    chain.append(event("build.two", verdicts.FAILED))
    lines = lines_of(filesystem, location)

    document = json.loads(lines[1])
    document["entry"]["verdict"] = verdicts.Passed.stored_name
    forged = ledger.Entry(
        sequence=1,
        stamp=document["entry"]["stamp"],
        event=event("build.two"),
    )
    document["link"] = ledger.link_after(
        identifiers.Digest(json.loads(lines[0])["link"]), forged
    ).hex
    lines[1] = json.dumps(document).encode()

    report = ledger.replay(lines, signer=signer(), head=chain.head())

    assert not report.intact
    assert report.first_break is not None
    assert report.first_break.cause is ledger.Break.MAC_MISMATCH


def test_a_deleted_entry_is_detected(
    chain: ledger.Ledger, filesystem: fake_files.MemoryFiles, location: proofs.StoreLocation
) -> None:
    for name in ("build.one", "build.two", "build.three"):
        chain.append(event(name))
    lines = lines_of(filesystem, location)

    report = ledger.replay(lines[:1] + lines[2:], signer=signer(), head=chain.head())

    assert not report.intact
    assert report.first_break is not None
    assert report.first_break.sequence == 2


def test_reordering_two_entries_is_detected(
    chain: ledger.Ledger, filesystem: fake_files.MemoryFiles, location: proofs.StoreLocation
) -> None:
    chain.append(event("build.one"))
    chain.append(event("build.two"))
    lines = lines_of(filesystem, location)

    report = ledger.replay([lines[1], lines[0]], signer=signer(), head=chain.head())

    assert not report.intact


def test_dropping_the_last_entry_is_detected_by_the_head(
    chain: ledger.Ledger, filesystem: fake_files.MemoryFiles, location: proofs.StoreLocation
) -> None:
    chain.append(event("build.one"))
    chain.append(event("build.two"))
    head = chain.head()
    lines = lines_of(filesystem, location)

    report = ledger.replay(lines[:-1], signer=signer(), head=head)

    assert not report.intact
    assert report.first_break is not None
    assert report.first_break.cause is ledger.Break.HEAD_AHEAD_OF_CHAIN


def test_an_empty_chain_under_a_head_is_detected(chain: ledger.Ledger) -> None:
    chain.append(event("build.one"))

    report = ledger.replay([], signer=signer(), head=chain.head())

    assert not report.intact


def test_the_wrong_key_cannot_confirm_a_chain(
    chain: ledger.Ledger, filesystem: fake_files.MemoryFiles, location: proofs.StoreLocation
) -> None:
    chain.append(event("build.one"))

    report = ledger.replay(
        lines_of(filesystem, location), signer=signer("another key"), head=chain.head()
    )

    assert not report.intact
    assert report.first_break is not None
    assert report.first_break.cause is ledger.Break.MAC_MISMATCH


def test_a_simulated_run_cannot_append(chain: ledger.Ledger) -> None:
    with pytest.raises(errors.Refusal) as raised:
        chain.append(event("build.one", environment=claims.EnvironmentKind.SIMULATED))

    assert raised.value.reason is refusals.RefusalReason.SIMULATED_ENVIRONMENT


def test_a_malformed_line_is_a_break_and_not_a_crash(chain: ledger.Ledger) -> None:
    report = ledger.replay([b"{not json"], signer=signer(), head=None)

    assert not report.intact
    assert report.first_break is not None
    assert report.first_break.cause is ledger.Break.MALFORMED_LINE


def test_the_chain_is_written_private(
    chain: ledger.Ledger, filesystem: fake_files.MemoryFiles, location: proofs.StoreLocation
) -> None:
    chain.append(event("build.one"))

    assert filesystem.mode_of(location.chain_path()).value == 0o600
    assert filesystem.mode_of(location.head_path()).value == 0o600


def test_the_key_is_not_rendered_by_the_signer() -> None:
    assert "chain key" not in repr(signer())


def test_a_second_ledger_continues_the_chain_rather_than_restarting_it(
    location: proofs.StoreLocation, filesystem: fake_files.MemoryFiles
) -> None:
    first = ledger.Ledger(
        location=location,
        filesystem=filesystem,
        signer=signer(),
        wallclock=fake_wallclock.FixedWallClock(),
    )
    first.append(event("build.one"))
    first.append(event("build.two"))

    resumed = ledger.Ledger(
        location=location,
        filesystem=filesystem,
        signer=signer(),
        wallclock=fake_wallclock.FixedWallClock(),
    )
    sealed = resumed.append(event("build.three"))

    lines, head = ledger.read_chain(location, filesystem)
    report = ledger.replay(lines, signer=signer(), head=head)

    assert sealed.entry.sequence == 2
    assert report.intact
    assert report.entries == 3


def test_an_unreadable_head_stops_the_chain_from_being_continued(
    location: proofs.StoreLocation, filesystem: fake_files.MemoryFiles
) -> None:
    filesystem.write_atomic(
        location.head_path(), b"{ truncated", mode=ledger.RECORD_MODE
    )

    with pytest.raises(errors.Refusal) as raised:
        ledger.Ledger(
            location=location,
            filesystem=filesystem,
            signer=signer(),
            wallclock=fake_wallclock.FixedWallClock(),
        )

    assert raised.value.reason is refusals.RefusalReason.STALE_EVIDENCE


def test_reading_an_absent_chain_reports_nothing_rather_than_failing(
    location: proofs.StoreLocation, filesystem: fake_files.MemoryFiles
) -> None:
    lines, head = ledger.read_chain(location, filesystem)

    assert lines == []
    assert head is None

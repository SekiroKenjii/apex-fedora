"""The rendering shows what the table holds, including what it refuses to stand on."""

from __future__ import annotations

from apex.attestation import attesting, columns, ledger, readerspecs, readiness, retracting
from apex.cli import rendering
from apex.kernel import claims, identifiers, verdicts

CANDIDATE = identifiers.Digest("c" * 64)


def attestation(check: str) -> attesting.Attestation:
    return attesting.Attestation(
        kind=ledger.EntryKind.IMPORTED,
        resolved=readiness.ResolvedRecord(
            check=identifiers.CheckId(check),
            verdict=verdicts.PASSED,
            environment=claims.EnvironmentKind.BUILD,
            candidate=CANDIDATE,
            proofs_intact=True,
            proof_count=1,
            imported=True,
        ),
        limits=attesting.LEGACY_LIMITS,
        origin=f"{check}.json",
    )


def table(*, strict: bool, faults: tuple[str, ...] = ()) -> columns.Table:
    reading = readerspecs.StoreReading(
        version=1, attestations=(attestation("build.one"),), candidate=CANDIDATE, faults=faults
    )
    outcome = readiness.Outcome(
        ready=False,
        verdicts={"build.one": verdicts.PASSED},
        counts={"PASS": 1},
        faults=(),
    )
    withheld: tuple[retracting.Withheld, ...] = ()
    if strict:
        outcome, withheld = retracting.retract(
            outcome, attestations=list(reading.attestations)
        )
    return columns.tabulate(
        reading=reading, outcome=outcome, withheld=withheld, strict=strict
    )


def test_the_rendering_names_every_heading() -> None:
    text = rendering.render(table(strict=False))

    for heading in rendering.HEADINGS:
        assert heading in text


def test_the_rendering_shows_the_imported_tally_and_the_store_version() -> None:
    text = rendering.render(table(strict=False))

    assert "imported" in text
    assert "1" in text


def test_the_rendering_shows_every_fault() -> None:
    text = rendering.render(table(strict=False, faults=("evidence.stale-or-unbound: one.json",)))

    assert "evidence.stale-or-unbound: one.json" in text


def test_a_strict_rendering_says_what_it_withheld() -> None:
    text = rendering.render(table(strict=True))

    assert verdicts.Passed.stored_name in text

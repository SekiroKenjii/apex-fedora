"""Where a record came from is a field on every row, never a string a renderer invents."""

from __future__ import annotations

from apex.attestation import attesting, columns, ledger, readerspecs, readiness, retracting
from apex.kernel import claims, identifiers, refusals, verdicts

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


def reading(*checks: str, faults: tuple[str, ...] = ()) -> readerspecs.StoreReading:
    return readerspecs.StoreReading(
        version=1,
        attestations=tuple(attestation(name) for name in checks),
        candidate=CANDIDATE,
        faults=faults,
    )


def outcome(
    faults: tuple[str, ...] = (),
    named: dict[str, verdicts.Verdict] | None = None,
    **by_check: verdicts.Verdict,
) -> readiness.Outcome:
    by_check = {**(named or {}), **by_check}
    counts: dict[str, int] = {}
    for verdict in by_check.values():
        counts[verdict.stored_name] = counts.get(verdict.stored_name, 0) + 1
    return readiness.Outcome(
        ready=not faults and all(item.permits_installation for item in by_check.values()),
        verdicts=dict(by_check),
        counts=counts,
        faults=faults,
    )


def test_an_imported_row_names_its_origin_and_both_permanent_limits() -> None:
    table = columns.tabulate(
        reading=reading("one"), outcome=outcome(one=verdicts.PASSED), withheld=(), strict=False
    )

    row = table.rows[0]
    assert row.origin is columns.Origin.IMPORTED
    assert set(row.limits) == attesting.LEGACY_LIMITS
    assert table.imported == 1


def test_a_check_with_no_record_is_absent_and_carries_no_limit() -> None:
    table = columns.tabulate(
        reading=reading(),
        outcome=outcome(one=verdicts.NotTested(refusals.RefusalReason.NO_VERIFIED_RESULT)),
        withheld=(),
        strict=False,
    )

    row = table.rows[0]
    assert row.origin is columns.Origin.ABSENT
    assert row.limits == ()
    assert table.imported == 0


def test_the_table_carries_every_fault_the_fold_and_the_reading_reported() -> None:
    """Without this a duplicate, an unknown check and an altered proof vanish from the view."""
    table = columns.tabulate(
        reading=reading("one", faults=("malformed.store-mark: damaged.json",)),
        outcome=outcome(("evidence.duplicate: one has two records",), one=verdicts.BLOCKED),
        withheld=(),
        strict=False,
    )

    assert len(table.faults) == 2
    assert any("duplicate" in fault for fault in table.faults)
    assert any("damaged.json" in fault for fault in table.faults)


def test_a_strict_row_shows_the_verdict_that_was_withheld() -> None:
    default = outcome(one=verdicts.PASSED)
    strict, withheld = retracting.retract(default, attestations=[attestation("one")])

    table = columns.tabulate(reading=reading("one"), outcome=strict, withheld=withheld, strict=True)

    assert table.strict
    assert table.rows[0].withheld == verdicts.PASSED


def test_a_table_standing_on_imported_passes_is_not_ready_even_when_every_check_passes() -> None:
    table = columns.tabulate(
        reading=reading("one", "two"),
        outcome=readiness.evaluate(
            required={"one": claims.EnvironmentKind.BUILD, "two": claims.EnvironmentKind.BUILD},
            records=[attestation("one").resolved, attestation("two").resolved],
            candidate=CANDIDATE,
        ),
        withheld=(),
        strict=False,
    )

    assert table.counts == {"PASS": 2}
    assert not table.ready


def test_the_rows_are_ordered_by_check() -> None:
    table = columns.tabulate(
        reading=reading("z.one", "a.two"),
        outcome=outcome(named={"z.one": verdicts.PASSED, "a.two": verdicts.PASSED}),
        withheld=(),
        strict=False,
    )

    assert [row.check for row in table.rows] == ["a.two", "z.one"]


def test_the_document_is_canonical_and_names_the_store_version() -> None:
    table = columns.tabulate(
        reading=reading("one"), outcome=outcome(one=verdicts.PASSED), withheld=(), strict=False
    )

    document = columns.document(table)

    assert document["version"] == 1
    assert document["imported"] == 1


def test_a_recorded_row_names_its_chain_origin_and_carries_no_limit() -> None:
    recorded = attesting.Attestation(
        kind=ledger.EntryKind.RECORDED,
        resolved=readiness.ResolvedRecord(
            check=identifiers.CheckId("image.lint"),
            verdict=verdicts.PASSED,
            environment=claims.EnvironmentKind.BUILD,
            candidate=CANDIDATE,
            proofs_intact=True,
            proof_count=2,
            imported=False,
        ),
        limits=frozenset(),
        origin="chain#4",
    )
    found = readerspecs.StoreReading(
        version=2, attestations=(recorded,), candidate=CANDIDATE, faults=()
    )
    outcome = readiness.evaluate(
        required={"image.lint": claims.EnvironmentKind.BUILD},
        records=found.records,
        candidate=CANDIDATE,
    )

    table = columns.tabulate(reading=found, outcome=outcome, withheld=(), strict=False)

    (row,) = table.rows
    assert row.origin is columns.Origin.RECORDED
    assert row.limits == ()
    assert table.imported == 0
    assert columns.document(table)["checks"][0]["origin"] == "recorded"  # type: ignore[index]

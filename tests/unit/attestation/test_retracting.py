"""Strict readiness withholds a claim. It never erases a finding.

The plan says strict treats every imported record as not tested. Read literally that also
demotes the six blocked records the operator recorded, and blocked is what a detected fault
looks like. `readiness._judge` exists to keep a fault from looking like a check nobody ran, so
strict narrows to verdicts that permit installation and leaves every finding standing.

The guard this replaces was `claims_less`, and it has no teeth here: NOT TESTED claims less
than BLOCKED, so it passes green on exactly the erasure it was offered as proof against.
"""

from __future__ import annotations

from apex.attestation import attesting, ledger, readiness, retracting
from apex.kernel import claims, identifiers, refusals, verdicts

CANDIDATE = identifiers.Digest("c" * 64)


def attestation(check: str, *, imported: bool = True) -> attesting.Attestation:
    kind = ledger.EntryKind.IMPORTED if imported else ledger.EntryKind.RECORDED
    return attesting.Attestation(
        kind=kind,
        resolved=readiness.ResolvedRecord(
            check=identifiers.CheckId(check),
            verdict=verdicts.PASSED,
            environment=claims.EnvironmentKind.BUILD,
            candidate=CANDIDATE,
            proofs_intact=True,
            proof_count=1,
            imported=imported,
        ),
        limits=attesting.LEGACY_LIMITS if imported else frozenset(),
        origin=f"{check}.json",
    )


def outcome(**verdict_by_check: verdicts.Verdict) -> readiness.Outcome:
    counts: dict[str, int] = {}
    for verdict in verdict_by_check.values():
        counts[verdict.stored_name] = counts.get(verdict.stored_name, 0) + 1
    return readiness.Outcome(
        ready=all(item.permits_installation for item in verdict_by_check.values()),
        verdicts=dict(verdict_by_check),
        counts=counts,
        faults=(),
    )


def test_strict_withholds_an_imported_pass() -> None:
    strict, withheld = retracting.retract(
        outcome(one=verdicts.PASSED), attestations=[attestation("one")]
    )

    assert not strict.verdict_of("one").permits_installation
    assert [item.check for item in withheld] == ["one"]


def test_strict_leaves_an_imported_blocked_exactly_as_the_default_fold_reported_it() -> None:
    """The property that distinguishes withholding a claim from erasing a finding."""
    default = outcome(
        one=verdicts.BLOCKED,
        two=verdicts.FAILED,
        three=verdicts.NotTested(refusals.RefusalReason.NO_VERIFIED_RESULT),
    )

    strict, withheld = retracting.retract(
        default,
        attestations=[attestation("one"), attestation("two"), attestation("three")],
    )

    for name, verdict in default.verdicts.items():
        assert strict.verdict_of(name) == verdict
    assert withheld == ()


def test_a_withheld_verdict_names_the_legacy_import_and_not_a_check_nobody_ran() -> None:
    strict, _ = retracting.retract(
        outcome(one=verdicts.PASSED), attestations=[attestation("one")]
    )

    stated = strict.verdict_of("one")
    assert isinstance(stated, verdicts.NotTested)
    assert stated.reason is refusals.RefusalReason.LEGACY_IMPORT_NOT_REPROVEN


def test_strict_reports_the_verdict_it_withheld() -> None:
    _, withheld = retracting.retract(
        outcome(one=verdicts.PASSED), attestations=[attestation("one")]
    )

    assert withheld[0].stated == verdicts.PASSED


def test_a_record_that_was_not_imported_is_left_alone() -> None:
    strict, withheld = retracting.retract(
        outcome(one=verdicts.PASSED), attestations=[attestation("one", imported=False)]
    )

    assert strict.verdict_of("one") == verdicts.PASSED
    assert withheld == ()


def test_strict_tolerates_an_imported_record_for_a_check_outside_the_catalogue() -> None:
    """The fold drops such a record with a fault, so its name never enters the verdict map."""
    strict, withheld = retracting.retract(
        outcome(one=verdicts.PASSED), attestations=[attestation("one"), attestation("stray")]
    )

    assert set(strict.verdicts) == {"one"}
    assert [item.check for item in withheld] == ["one"]


def test_strict_never_raises_readiness_and_the_counts_still_sum_to_the_catalogue() -> None:
    default = outcome(one=verdicts.PASSED, two=verdicts.PASSED, three=verdicts.BLOCKED)

    strict, _ = retracting.retract(
        default, attestations=[attestation("one"), attestation("two")]
    )

    assert not strict.ready
    assert sum(strict.counts.values()) == len(default.verdicts)


def test_strict_adds_no_fault() -> None:
    """A demotion is policy. Reporting it as a fault would perturb what the gate compares."""
    strict, _ = retracting.retract(
        outcome(one=verdicts.PASSED), attestations=[attestation("one")]
    )

    assert strict.faults == ()


def test_a_store_with_nothing_imported_is_returned_unchanged() -> None:
    default = outcome(one=verdicts.PASSED, two=verdicts.BLOCKED)

    strict, withheld = retracting.retract(default, attestations=[])

    assert strict.verdicts == default.verdicts
    assert strict.ready == default.ready
    assert withheld == ()

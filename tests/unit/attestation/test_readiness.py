"""Readiness is a pure total fold over the catalogue, and it does no input or output.

It receives resolved records. Reading files, re-hashing proofs and replaying a chain all
happen before it, so the decision itself can be tested exhaustively without a filesystem.
"""

from __future__ import annotations

import dataclasses

import pytest

from apex.attestation import readiness
from apex.kernel import claims, identifiers, refusals, verdicts

DIGEST = identifiers.Digest("a" * 64)
OTHER = identifiers.Digest("b" * 64)


def resolved(
    check: str,
    verdict: verdicts.Verdict,
    *,
    environment: claims.EnvironmentKind = claims.EnvironmentKind.BUILD,
    candidate: identifiers.Digest = DIGEST,
    proofs_intact: bool = True,
    proof_count: int = 1,
) -> readiness.ResolvedRecord:
    return readiness.ResolvedRecord(
        check=identifiers.CheckId(check),
        verdict=verdict,
        environment=environment,
        candidate=candidate,
        proofs_intact=proofs_intact,
        proof_count=proof_count,
        imported=False,
    )


def catalogue(*entries: tuple[str, claims.EnvironmentKind]) -> dict[str, claims.EnvironmentKind]:
    return dict(entries)


def test_a_catalogue_with_no_record_is_entirely_untested() -> None:
    outcome = readiness.evaluate(
        required=catalogue(("a.one", claims.EnvironmentKind.BUILD)), records=(), candidate=DIGEST
    )

    assert not outcome.ready
    assert outcome.counts["NOT TESTED"] == 1


def test_a_single_pass_over_a_single_check_is_ready() -> None:
    outcome = readiness.evaluate(
        required=catalogue(("a.one", claims.EnvironmentKind.BUILD)),
        records=(resolved("a.one", verdicts.PASSED),),
        candidate=DIGEST,
    )

    assert outcome.ready


def test_one_untested_check_among_passes_blocks_installation() -> None:
    outcome = readiness.evaluate(
        required=catalogue(
            ("a.one", claims.EnvironmentKind.BUILD), ("a.two", claims.EnvironmentKind.BUILD)
        ),
        records=(resolved("a.one", verdicts.PASSED),),
        candidate=DIGEST,
    )

    assert not outcome.ready


def test_an_empty_catalogue_is_not_ready() -> None:
    assert not readiness.evaluate(required={}, records=(), candidate=DIGEST).ready


def test_no_candidate_is_not_ready() -> None:
    outcome = readiness.evaluate(
        required=catalogue(("a.one", claims.EnvironmentKind.BUILD)),
        records=(resolved("a.one", verdicts.PASSED),),
        candidate=None,
    )

    assert not outcome.ready


def test_a_record_bound_to_another_candidate_is_blocked_not_untested() -> None:
    outcome = readiness.evaluate(
        required=catalogue(("a.one", claims.EnvironmentKind.BUILD)),
        records=(resolved("a.one", verdicts.PASSED, candidate=OTHER),),
        candidate=DIGEST,
    )

    assert outcome.verdict_of("a.one") == verdicts.BLOCKED
    assert not outcome.ready


def test_an_altered_proof_blocks_rather_than_disappearing() -> None:
    """A detected fault and a check nobody ran must never become the same value."""
    outcome = readiness.evaluate(
        required=catalogue(("a.one", claims.EnvironmentKind.BUILD)),
        records=(resolved("a.one", verdicts.PASSED, proofs_intact=False),),
        candidate=DIGEST,
    )

    assert outcome.verdict_of("a.one") == verdicts.BLOCKED
    assert outcome.faults


def test_a_pass_without_proof_is_blocked() -> None:
    outcome = readiness.evaluate(
        required=catalogue(("a.one", claims.EnvironmentKind.BUILD)),
        records=(resolved("a.one", verdicts.PASSED, proof_count=0),),
        candidate=DIGEST,
    )

    assert outcome.verdict_of("a.one") == verdicts.BLOCKED


def test_a_hardware_check_satisfied_by_a_virtual_machine_is_blocked() -> None:
    outcome = readiness.evaluate(
        required=catalogue(("audio.speakers", claims.EnvironmentKind.PHYSICAL)),
        records=(
            resolved("audio.speakers", verdicts.PASSED, environment=claims.EnvironmentKind.VM),
        ),
        candidate=DIGEST,
    )

    assert outcome.verdict_of("audio.speakers") == verdicts.BLOCKED


def test_a_record_for_a_check_outside_the_catalogue_is_a_fault() -> None:
    outcome = readiness.evaluate(
        required=catalogue(("a.one", claims.EnvironmentKind.BUILD)),
        records=(resolved("a.gone", verdicts.PASSED),),
        candidate=DIGEST,
    )

    assert any("a.gone" in fault for fault in outcome.faults)
    assert not outcome.ready


def test_two_records_for_one_check_are_a_fault() -> None:
    outcome = readiness.evaluate(
        required=catalogue(("a.one", claims.EnvironmentKind.BUILD)),
        records=(resolved("a.one", verdicts.PASSED), resolved("a.one", verdicts.PASSED)),
        candidate=DIGEST,
    )

    assert outcome.faults
    assert not outcome.ready


def test_an_imported_record_never_makes_a_candidate_ready() -> None:
    imported = readiness.ResolvedRecord(
        check=identifiers.CheckId("a.one"),
        verdict=verdicts.PASSED,
        environment=claims.EnvironmentKind.BUILD,
        candidate=DIGEST,
        proofs_intact=True,
        proof_count=1,
        imported=True,
    )

    outcome = readiness.evaluate(
        required=catalogue(("a.one", claims.EnvironmentKind.BUILD)),
        records=(imported,),
        candidate=DIGEST,
    )

    assert not outcome.ready
    assert outcome.verdict_of("a.one") == verdicts.PASSED


def test_the_fold_is_the_same_whatever_order_the_records_arrive_in() -> None:
    required = catalogue(
        ("a.one", claims.EnvironmentKind.BUILD), ("a.two", claims.EnvironmentKind.BUILD)
    )
    records = (resolved("a.one", verdicts.PASSED), resolved("a.two", verdicts.BLOCKED))

    first = readiness.evaluate(required=required, records=records, candidate=DIGEST)
    second = readiness.evaluate(
        required=required, records=tuple(reversed(records)), candidate=DIGEST
    )

    assert first.counts == second.counts
    assert first.ready == second.ready


def test_a_retracted_result_is_distinguishable_from_one_never_run() -> None:
    retracted = readiness.ResolvedRecord(
        check=identifiers.CheckId("a.one"),
        verdict=verdicts.NotTested(refusals.RefusalReason.RETRACTED_BY_OPERATOR),
        environment=claims.EnvironmentKind.BUILD,
        candidate=DIGEST,
        proofs_intact=True,
        proof_count=0,
        imported=False,
    )

    outcome = readiness.evaluate(
        required=catalogue(("a.one", claims.EnvironmentKind.BUILD)),
        records=(retracted,),
        candidate=DIGEST,
    )

    stated = outcome.verdict_of("a.one")
    assert isinstance(stated, verdicts.NotTested)
    assert stated.reason is refusals.RefusalReason.RETRACTED_BY_OPERATOR


def test_the_counts_add_up_to_the_catalogue() -> None:
    required = catalogue(
        ("a.one", claims.EnvironmentKind.BUILD),
        ("a.two", claims.EnvironmentKind.BUILD),
        ("a.three", claims.EnvironmentKind.BUILD),
    )

    outcome = readiness.evaluate(
        required=required, records=(resolved("a.one", verdicts.PASSED),), candidate=DIGEST
    )

    assert sum(outcome.counts.values()) == len(required)


@pytest.mark.parametrize(
    "verdict",
    [
        verdicts.PASSED,
        verdicts.FAILED,
        verdicts.BLOCKED,
        verdicts.NotTested(refusals.RefusalReason.NO_VERIFIED_RESULT),
    ],
)
def test_the_judgement_of_a_record_does_not_depend_on_whether_it_was_imported(
    verdict: verdicts.Verdict,
) -> None:
    """The pin under the claim that importing moves no number.

    It passes against the fold as written, which is the point: it must exist before imported
    records start flowing, so that teaching `_judge` to read the flag fails loudly instead of
    quietly moving eighteen, six and thirty-eight.
    """
    required = catalogue(("a.one", claims.EnvironmentKind.BUILD))
    both = [
        readiness.evaluate(
            required=required,
            records=[dataclasses.replace(resolved("a.one", verdict), imported=flag)],
            candidate=DIGEST,
        )
        for flag in (False, True)
    ]

    assert both[0].verdicts == both[1].verdicts
    assert both[0].counts == both[1].counts

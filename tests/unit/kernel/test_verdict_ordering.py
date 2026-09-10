"""Readiness is a conjunction, never a lattice rollup.

`meet` has NotTested as its identity, which is correct for combining what one run observed and
wrong for deciding whether every check passed. Folding 62 checks where 38 were never run would
report the verdict of the 24 that were.
"""

from __future__ import annotations

from apex.kernel import refusals, verdicts

NOT_TESTED = verdicts.NotTested(refusals.RefusalReason.NO_VERIFIED_RESULT)


def test_a_rollup_ignores_untested_checks_which_is_why_it_cannot_gate() -> None:
    observed = [verdicts.PASSED, NOT_TESTED, NOT_TESTED]

    assert verdicts.meet(verdicts.meet(observed[0], observed[1]), observed[2]) == verdicts.PASSED


def test_requiring_all_refuses_when_any_check_was_never_run() -> None:
    assert not verdicts.require_all([verdicts.PASSED, NOT_TESTED])


def test_requiring_all_accepts_only_a_complete_set_of_passes() -> None:
    assert verdicts.require_all([verdicts.PASSED, verdicts.PASSED])


def test_requiring_all_of_nothing_is_false() -> None:
    """An empty catalogue must not read as ready."""
    assert not verdicts.require_all([])


def test_requiring_all_refuses_a_blocked_check() -> None:
    assert not verdicts.require_all([verdicts.PASSED, verdicts.BLOCKED])


def test_retracting_a_blocked_result_to_untested_is_not_an_improvement() -> None:
    assert verdicts.claims_less(verdicts.BLOCKED, NOT_TESTED)


def test_retracting_a_pass_to_untested_claims_less() -> None:
    assert verdicts.claims_less(verdicts.PASSED, NOT_TESTED)


def test_a_pass_replacing_an_untested_claims_more() -> None:
    assert not verdicts.claims_less(NOT_TESTED, verdicts.PASSED)


def test_a_failure_replacing_a_pass_claims_less() -> None:
    assert verdicts.claims_less(verdicts.PASSED, verdicts.FAILED)


def test_an_unchanged_verdict_claims_neither_more_nor_less() -> None:
    assert not verdicts.claims_less(verdicts.PASSED, verdicts.PASSED)


def test_meet_and_claims_less_disagree_on_the_case_that_matters() -> None:
    """`meet(PASS, NOT TESTED)` is PASS, yet retracting a pass claims less."""
    assert verdicts.meet(verdicts.PASSED, NOT_TESTED) == verdicts.PASSED
    assert verdicts.claims_less(verdicts.PASSED, NOT_TESTED)

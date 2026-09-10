"""The verdict lattice makes refusal to overclaim a theorem, not a discipline."""

from __future__ import annotations

import itertools

import pytest

from apex.kernel import errors, refusals, verdicts

NOT_TESTED = verdicts.NotTested(refusals.RefusalReason.NO_VERIFIED_RESULT)
ALL = (verdicts.PASSED, verdicts.FAILED, verdicts.BLOCKED, NOT_TESTED)


def test_the_four_stored_names_round_trip() -> None:
    for verdict in ALL:
        assert verdicts.parse(verdict.stored_name, reason=NOT_TESTED.reason) == verdict


def test_the_stored_names_match_what_the_evidence_files_hold() -> None:
    assert {verdict.stored_name for verdict in ALL} == {"PASS", "FAIL", "BLOCKED", "NOT TESTED"}


def test_not_tested_is_the_identity_element() -> None:
    for verdict in ALL:
        assert verdicts.meet(verdict, NOT_TESTED) == verdict
        assert verdicts.meet(NOT_TESTED, verdict) == verdict


def test_meet_is_commutative() -> None:
    for left, right in itertools.product(ALL, repeat=2):
        assert verdicts.meet(left, right) == verdicts.meet(right, left)


def test_meet_is_associative() -> None:
    for left, middle, right in itertools.product(ALL, repeat=3):
        assert verdicts.meet(verdicts.meet(left, middle), right) == verdicts.meet(
            left, verdicts.meet(middle, right)
        )


def test_no_combination_raises_a_set_without_a_pass_to_a_pass() -> None:
    for left, right in itertools.product(ALL, repeat=2):
        if left != verdicts.PASSED and right != verdicts.PASSED:
            assert verdicts.meet(left, right) != verdicts.PASSED


def test_a_failure_dominates_a_pass() -> None:
    assert verdicts.meet(verdicts.PASSED, verdicts.FAILED) == verdicts.FAILED


def test_folding_an_empty_collection_is_not_tested() -> None:
    assert verdicts.fold([], reason=NOT_TESTED.reason) == NOT_TESTED


def test_folding_all_passes_is_a_pass() -> None:
    assert verdicts.fold([verdicts.PASSED] * 5, reason=NOT_TESTED.reason) == verdicts.PASSED


def test_only_a_pass_permits_installation() -> None:
    assert verdicts.PASSED.permits_installation
    for verdict in (verdicts.FAILED, verdicts.BLOCKED, NOT_TESTED):
        assert not verdict.permits_installation


def test_not_tested_carries_its_reason() -> None:
    assert NOT_TESTED.reason is refusals.RefusalReason.NO_VERIFIED_RESULT


def test_an_unknown_stored_name_is_refused() -> None:
    with pytest.raises(errors.Refusal) as raised:
        verdicts.parse("MAYBE", reason=NOT_TESTED.reason)

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_VERDICT

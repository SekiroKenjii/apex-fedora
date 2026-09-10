"""Errors are typed by what the caller should do about them."""

from __future__ import annotations

import pytest

from apex.kernel import errors, refusals


def test_every_project_error_descends_from_one_root() -> None:
    for kind in (
        errors.Refusal, errors.PreconditionUnmet, errors.VerificationFailed,
        errors.PortFailure, errors.RegistrationError,
    ):
        assert issubclass(kind, errors.ApexError)


def test_each_error_carries_its_own_exit_code() -> None:
    codes = {
        errors.Refusal: 2,
        errors.PreconditionUnmet: 3,
        errors.VerificationFailed: 4,
        errors.PortFailure: 5,
    }
    for kind, code in codes.items():
        assert kind.exit_code == code


def test_the_exit_codes_are_distinct() -> None:
    codes = [
        errors.Refusal.exit_code, errors.PreconditionUnmet.exit_code,
        errors.VerificationFailed.exit_code, errors.PortFailure.exit_code,
        errors.INTERNAL_DEFECT_EXIT_CODE,
    ]

    assert len(set(codes)) == len(codes)


def test_a_refusal_carries_a_reason_a_subject_and_a_remedy() -> None:
    refusal = errors.Refusal(
        refusals.RefusalReason.MALFORMED_DIGEST, subject="candidate.json", remedy="supply a digest"
    )

    assert refusal.reason is refusals.RefusalReason.MALFORMED_DIGEST
    assert refusal.subject == "candidate.json"
    assert refusal.remedy == "supply a digest"


def test_a_refusal_renders_its_reason_rather_than_only_prose() -> None:
    refusal = errors.Refusal(refusals.RefusalReason.MALFORMED_DIGEST, subject="x")

    assert refusals.RefusalReason.MALFORMED_DIGEST.value in str(refusal)


def test_a_verification_failure_records_what_was_expected_and_seen() -> None:
    failure = errors.VerificationFailed(check="image.lint", expected="0 warnings", observed="3")

    assert failure.check == "image.lint"
    assert failure.expected == "0 warnings"
    assert failure.observed == "3"


def test_an_internal_defect_is_not_a_project_error() -> None:
    assert not issubclass(errors.InternalDefect, errors.ApexError)


def test_a_refusal_is_catchable_as_the_root_error() -> None:
    with pytest.raises(errors.ApexError):
        raise errors.Refusal(refusals.RefusalReason.MALFORMED_IDENTIFIER, subject="x")

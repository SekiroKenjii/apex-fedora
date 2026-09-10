"""One subject line, and every reason it can be refused, reported together.

The guard being replaced raises on the first failure, so a message carrying both a body and a
co-author trailer is reported as a body alone and the author fixes one thing at a time.
"""

from __future__ import annotations

import pytest

from apex.kernel import refusals
from apex.workspace import gitguarding, messagerules, rulespecs


def reasons(raw: str) -> set[refusals.RefusalReason]:
    return {
        finding.reason
        for finding in gitguarding.judge_message(
            rulespecs.MessageSubject(raw), rules=messagerules.registered()
        )
    }


def test_a_well_formed_subject_is_accepted() -> None:
    assert reasons("feat(cli): replace the dispatch chain\n") == set()


def test_the_seventy_two_character_boundary_is_inclusive() -> None:
    """Pinned by nothing today: the existing cases use seventy three and seventy five."""
    body = "fix: "
    assert reasons(body + "a" * (72 - len(body)) + "\n") == set()
    assert refusals.RefusalReason.COMMIT_SUBJECT_TOO_LONG in reasons(
        body + "a" * (73 - len(body)) + "\n"
    )


def test_a_carriage_return_is_refused_on_its_own_terms() -> None:
    """The subject matches the pattern, fits the width and holds no second line."""
    stated = reasons("fix: a\rb\n")

    assert stated == {refusals.RefusalReason.COMMIT_CARRIAGE_RETURN}


def test_a_message_ending_in_a_carriage_return_and_a_newline_is_refused() -> None:
    assert refusals.RefusalReason.COMMIT_CARRIAGE_RETURN in reasons("fix: hello\r\n")


@pytest.mark.parametrize("bad", ["nope: hello", "feat hello", "feat(): hello", "feat: ", ""])
def test_a_subject_outside_the_convention_is_refused(bad: str) -> None:
    assert refusals.RefusalReason.COMMIT_SUBJECT_MALFORMED in reasons(bad + "\n")


def test_a_body_is_a_second_line_even_when_it_is_blank() -> None:
    assert refusals.RefusalReason.COMMIT_HAS_BODY in reasons("fix: hello\n\n")


def test_a_co_author_trailer_is_refused_in_any_capitalisation() -> None:
    for spelling in ("Co-authored-by", "co-authored-by", "CO-AUTHORED-BY", "Co-Authored-By"):
        assert refusals.RefusalReason.VENDOR_ATTRIBUTION_PRESENT in reasons(
            f"fix: hello\n\n{spelling}: someone\n"
        )


def test_one_message_reports_the_body_and_the_trailer_together() -> None:
    """Impossible under a guard that raises on the first failure."""
    stated = reasons("fix: hello\n\nCo-authored-by: someone\n")

    assert refusals.RefusalReason.COMMIT_HAS_BODY in stated
    assert refusals.RefusalReason.VENDOR_ATTRIBUTION_PRESENT in stated


def test_the_refusals_do_not_depend_on_the_order_rules_were_registered() -> None:
    subject = rulespecs.MessageSubject("fix: hello\n\nCo-authored-by: someone\n")
    forward = messagerules.registered()

    assert {f.reason for f in gitguarding.judge_message(subject, rules=forward)} == {
        f.reason for f in gitguarding.judge_message(subject, rules=tuple(reversed(forward)))
    }

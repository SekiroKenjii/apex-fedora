"""An answer is met when the hook named every rule the question expected, and no rule when
none was expected; a report passes only when every answer is met."""

from __future__ import annotations

from pathlib import Path

from apex.kernel import verdicts
from apex.workspace import hookproving


def test_a_permitting_answer_is_met_only_when_no_rule_was_expected() -> None:
    assert hookproving.Answer("clean", (), ()).met
    assert not hookproving.Answer("clean", (), ("repository.private-document",)).met


def test_a_refusing_answer_is_met_when_the_expected_rules_are_among_those_named() -> None:
    named = ("repository.private-document", "repository.environment-file")

    assert hookproving.Answer("private", ("repository.private-document",), named).met
    assert not hookproving.Answer("private", ("repository.pem-private-key",), named).met
    assert not hookproving.Answer("private", ("repository.private-document",), ()).met


def test_a_report_fails_on_one_unmet_answer_and_carries_every_answer() -> None:
    met = hookproving.Answer("clean", (), ())
    unmet = hookproving.Answer("private", ("repository.private-document",), ())

    passed = hookproving.proven(hookproving.PRIVATE_STAGE, Path("/tmp/r"), [met])
    failed = hookproving.proven(hookproving.PRIVATE_STAGE, Path("/tmp/r"), [met, unmet])

    assert passed.verdict is verdicts.PASSED
    assert failed.verdict is verdicts.FAILED
    assert failed.observations["check"] == "git.private-stage"
    assert failed.observations["answers"] == [
        {"question": "clean", "expected": [], "found": [], "met": True},
        {
            "question": "private",
            "expected": ["repository.private-document"],
            "found": [],
            "met": False,
        },
    ]


def test_every_question_names_the_rule_it_expects_by_its_registered_name() -> None:
    expected = {
        rule for question in (*hookproving.MESSAGES, *hookproving.STAGED) for rule in question[-1]
    }

    assert expected == {
        "commit.subject-malformed",
        "commit.subject-too-long",
        "commit.has-body",
        "commit.co-author-trailer",
        "commit.carriage-return",
        "repository.private-document",
        "repository.pem-private-key",
        "repository.local-only-content",
        "repository.blob-contains-nul",
    }

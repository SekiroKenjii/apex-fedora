"""A credentials document, which this project writes and the guard it replaces permits."""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.credential-document")
NAME = "credentials.json"


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    if subject.path.name_lowered != NAME:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_CREDENTIAL_DOCUMENT,
            subject=subject.path.value,
            remedy="keep credentials beside the machine that uses them",
        ),
    )


entryrules.declare(
    rulespecs.EntryRule(
        id=RULE,
        origin=ruleorigins.Introduced(
            phase="P12",
            why=(
                "the guard it replaces matches key formats and service tokens, and nothing "
                "this project actually writes; the frozen inventory holds nine of these"
            ),
        ),
        inspect=inspect,
    )
)

"""A subject that does not fit the width a log is read at."""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import messagerules, ruleorigins, rulespecs

RULE = identifiers.RuleId("commit.subject-too-long")
LIMIT = 72


def inspect(subject: rulespecs.MessageSubject) -> Sequence[rulespecs.Finding]:
    text = messagerules.subject_line(subject)
    if len(text) <= LIMIT:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.COMMIT_SUBJECT_TOO_LONG,
            subject=f"the subject is {len(text)} characters",
            remedy="say it in seventy two characters or fewer",
        ),
    )


messagerules.declare(
    rulespecs.MessageRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.VALIDATE_SUBJECT),
        inspect=inspect,
    )
)

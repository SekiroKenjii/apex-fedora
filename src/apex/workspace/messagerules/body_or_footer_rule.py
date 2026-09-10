"""A commit carries one line. Detail belongs in the pull request or the issue.

Git supplies the final newline, so it is removed before this looks. Anything left is a second
line, and a blank body is still a second line.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import messagerules, ruleorigins, rulespecs

RULE = identifiers.RuleId("commit.has-body")
LINE_BREAK = "\n"


def inspect(subject: rulespecs.MessageSubject) -> Sequence[rulespecs.Finding]:
    text = messagerules.subject_line(subject)
    if LINE_BREAK not in text:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.COMMIT_HAS_BODY,
            subject="the message carries more than one line",
            remedy="put the detail in the pull request or the issue",
        ),
    )


messagerules.declare(
    rulespecs.MessageRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.VALIDATE_SUBJECT),
        inspect=inspect,
    )
)

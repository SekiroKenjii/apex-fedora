"""A carriage return anywhere in the subject.

Independently load bearing, and easy to lose in a decomposition. A subject like `fix: a\rb`
matches the conventional pattern, is well under the length limit and holds no second line, so
this term is the only thing that refuses it. Any message ending in a carriage return and a
newline reaches it too.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import messagerules, ruleorigins, rulespecs

RULE = identifiers.RuleId("commit.carriage-return")
CARRIAGE_RETURN = "\r"


def inspect(subject: rulespecs.MessageSubject) -> Sequence[rulespecs.Finding]:
    text = messagerules.subject_line(subject)
    if CARRIAGE_RETURN not in text:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.COMMIT_CARRIAGE_RETURN,
            subject="the subject carries a carriage return",
            remedy="write the subject with no carriage return",
        ),
    )


messagerules.declare(
    rulespecs.MessageRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.VALIDATE_SUBJECT),
        inspect=inspect,
    )
)

"""A co-author trailer, in any capitalisation.

The repository records a single author. This rule holds the only producer of the attribution
refusal, so the vocabulary member is not a declaration nobody makes.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import messagerules, ruleorigins, rulespecs

RULE = identifiers.RuleId("commit.co-author-trailer")
TRAILER = "co-authored-by"


def inspect(subject: rulespecs.MessageSubject) -> Sequence[rulespecs.Finding]:
    text = messagerules.subject_line(subject)
    if TRAILER not in text.lower():
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.VENDOR_ATTRIBUTION_PRESENT,
            subject="the message carries a co-author trailer",
            remedy="commit under one author",
        ),
    )


messagerules.declare(
    rulespecs.MessageRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.VALIDATE_SUBJECT),
        inspect=inspect,
    )
)

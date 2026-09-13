"""A tracked path never steps outside the tree that contains it."""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.path-escapes")


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    if not subject.path.traverses_upward:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_PATH_ESCAPES,
            subject=subject.path.value,
            remedy="a tracked path stays inside the repository",
        ),
    )


entryrules.declare(
    rulespecs.EntryRule(
        id=RULE, origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.PERMITTED), inspect=inspect
    )
)

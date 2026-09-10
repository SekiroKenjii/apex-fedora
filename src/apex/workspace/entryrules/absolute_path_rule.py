"""A tracked path is always relative to the repository root."""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.absolute-path")


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    if not subject.path.is_absolute:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_ABSOLUTE_PATH,
            subject=subject.path.value,
            remedy="name the file relative to the repository root",
        ),
    )


entryrules.declare(
    rulespecs.EntryRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.PERMITTED),
        inspect=inspect,
    )
)

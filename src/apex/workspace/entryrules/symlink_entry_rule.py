"""A link in the build source names a file the build never reads."""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals, treerows
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.entry-is-a-symlink")


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    if subject.mode is not treerows.EntryMode.SYMLINK:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.PATH_IS_A_SYMLINK,
            subject=subject.path.value,
            remedy="commit the file the link points at",
        ),
    )


entryrules.declare(
    rulespecs.EntryRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.INSPECT_BLOB),
        inspect=inspect,
    )
)

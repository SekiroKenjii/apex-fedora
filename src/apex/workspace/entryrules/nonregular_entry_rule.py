"""Anything that is neither a file, an executable nor a link.

Written as the complement of the modes that are understood, so a mode nobody anticipated is
refused rather than falling through the gap between two rules that each name one kind.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals, treerows
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.entry-not-regular")
UNDERSTOOD = frozenset(
    {
        treerows.EntryMode.REGULAR,
        treerows.EntryMode.EXECUTABLE,
        treerows.EntryMode.SYMLINK,
    }
)


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    if subject.mode in UNDERSTOOD:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.ARCHIVE_ENTRY_NOT_REGULAR,
            subject=f"{subject.path.value} is mode {subject.mode.value}",
            remedy="a submodule needs a reviewed packaging route",
        ),
    )



entryrules.declare(
    rulespecs.EntryRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.INSPECT_BLOB),
        inspect=inspect,
    )
)

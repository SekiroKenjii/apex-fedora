"""A source file large enough to need a reviewed packaging route.

Decided from the size the object database reports, so an oversize file is refused without its
bytes ever being read.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, quantities, refusals
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.blob-too-large")
MAXIMUM = quantities.ByteCount(20 * 1024 * 1024)


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    if subject.size is None or subject.size.value <= MAXIMUM.value:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_BLOB_TOO_LARGE,
            subject=f"{subject.path.value} is {subject.size.value} bytes",
            remedy="package a large input separately and reference it",
        ),
    )



entryrules.declare(
    rulespecs.EntryRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.INSPECT_BLOB),
        inspect=inspect,
    )
)

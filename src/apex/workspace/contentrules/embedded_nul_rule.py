"""Text that carries a zero byte.

Genuinely separate from the decoding rule: a payload can decode cleanly and still be a record
of something a machine emitted rather than something a person wrote.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import contentrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.blob-contains-nul")
NUL = b"\x00"


def inspect(subject: rulespecs.ContentSubject) -> Sequence[rulespecs.Finding]:
    if NUL not in subject.payload:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_BLOB_CONTAINS_NUL,
            subject=subject.path.value,
            remedy="binary source needs a reviewed packaging route",
        ),
    )


contentrules.declare(
    rulespecs.ContentRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.INSPECT_BLOB),
        inspect=inspect,
    )
)

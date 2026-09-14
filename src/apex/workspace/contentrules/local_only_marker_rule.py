"""A document that marks itself as written for this machine only.

The marker is assembled rather than written out, because a rule that carries the literal
would refuse its own source file.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import contentrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.local-only-content")
MARKER = b"<!-- apex-" + b"local-only -->"


def inspect(subject: rulespecs.ContentSubject) -> Sequence[rulespecs.Finding]:
    if MARKER not in subject.payload:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_LOCAL_ONLY_CONTENT,
            subject=subject.path.value,
            remedy="the document says it is local, so keep it local",
        ),
    )


contentrules.declare(
    rulespecs.ContentRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.INSPECT_BLOB),
        inspect=inspect,
    )
)

"""Documents that are written for this machine and never for the repository.

All eight names the guard being replaced carries live here together. Splitting the two key
names out into a rule that refuses more would make them permitted in the configuration that
proves the transcription faithful, which is the one place a gap would not be visible.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.private-document")
NAMES = frozenset(
    {
        "agents.md",
        "claude.md",
        "handover.md",
        "memory.md",
        ".env",
        "cosign.key",
        "id_rsa",
        "id_ed25519",
    }
)


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    if subject.path.name_lowered not in NAMES:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_PRIVATE_DOCUMENT,
            subject=subject.path.value,
            remedy="keep it local and remove it from the index before committing",
        ),
    )


entryrules.declare(
    rulespecs.EntryRule(
        id=RULE, origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.PERMITTED), inspect=inspect
    )
)

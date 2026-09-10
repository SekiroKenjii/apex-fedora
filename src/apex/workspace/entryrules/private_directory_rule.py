"""Directories whose whole contents are local.

Only the components above the file are examined, so a file named `logs` is an ordinary file
while anything under a directory named `logs` is not.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.private-directory")
DIRECTORIES = frozenset(
    {
        ".claude",
        ".codex",
        ".agents",
        "agent",
        "evidence",
        "private",
        "logs",
        "fprint",
        "fingerprints",
        "__pycache__",
    }
)


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    offending = [
        component
        for component in subject.path.directory_components
        if component.lower() in DIRECTORIES
    ]
    if not offending:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_PRIVATE_DIRECTORY,
            subject=f"{subject.path.value} is under {offending[0]}",
            remedy="everything below that directory is local to this machine",
        ),
    )


entryrules.declare(
    rulespecs.EntryRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.PERMITTED),
        inspect=inspect,
    )
)

"""Artifacts a build produces, and captures a machine records.

The last suffix decides, so `x.tar.gz` is permitted and `x.txt.log` is not.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import entryrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.private-artifact")
SUFFIXES = frozenset(
    {
        ".log",
        ".pcap",
        ".pcapng",
        ".qcow2",
        ".iso",
        ".key",
        ".pem",
        ".p12",
        ".pfx",
        ".pyc",
        ".fpt",
        ".fpm",
    }
)


def inspect(subject: rulespecs.EntrySubject) -> Sequence[rulespecs.Finding]:
    if subject.path.suffix_lowered not in SUFFIXES:
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_PRIVATE_ARTIFACT,
            subject=subject.path.value,
            remedy="an artifact or a capture belongs outside the repository",
        ),
    )


entryrules.declare(
    rulespecs.EntryRule(
        id=RULE, origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.PERMITTED), inspect=inspect
    )
)

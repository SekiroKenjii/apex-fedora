"""The shape a subject takes: a type, an optional scope, then a description.

The type set and the pattern are the ones the repository already requires.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import messagerules, ruleorigins, rulespecs

RULE = identifiers.RuleId("commit.subject-malformed")
TYPES = (
    "feat",
    "fix",
    "docs",
    "style",
    "refactor",
    "perf",
    "test",
    "build",
    "ci",
    "chore",
    "revert",
)
PATTERN = re.compile(rf"(?:{'|'.join(TYPES)})(?:\([a-z0-9][a-z0-9._/-]*\))?: [^\s].*")


def inspect(subject: rulespecs.MessageSubject) -> Sequence[rulespecs.Finding]:
    text = messagerules.subject_line(subject)
    if PATTERN.fullmatch(text):
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.COMMIT_SUBJECT_MALFORMED,
            subject=text or "(empty)",
            remedy="write type(scope): description, with a permitted type",
        ),
    )


messagerules.declare(
    rulespecs.MessageRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.VALIDATE_SUBJECT),
        inspect=inspect,
    )
)

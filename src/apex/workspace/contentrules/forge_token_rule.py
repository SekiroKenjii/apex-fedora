"""A forge access token.

Nothing this project writes produces one of these. It stays because removing a refusal is a
weakening, whatever the local hit rate is.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import contentrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.forge-token")
PATTERN = re.compile(
    rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b"
)


def inspect(subject: rulespecs.ContentSubject) -> Sequence[rulespecs.Finding]:
    if not PATTERN.search(subject.payload):
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_SECRET_MATERIAL,
            subject=subject.path.value,
            remedy="revoke the token and keep it out of the repository",
        ),
    )



contentrules.declare(
    rulespecs.ContentRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.INSPECT_BLOB),
        inspect=inspect,
    )
)

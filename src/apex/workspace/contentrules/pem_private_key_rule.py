"""A private key in any of the encodings that announce themselves in a header."""

from __future__ import annotations

import re
from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import contentrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.pem-private-key")
PATTERN = re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")


def inspect(subject: rulespecs.ContentSubject) -> Sequence[rulespecs.Finding]:
    if not PATTERN.search(subject.payload):
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.REPOSITORY_SECRET_MATERIAL,
            subject=subject.path.value,
            remedy="rotate the key and keep it off the repository",
        ),
    )



contentrules.declare(
    rulespecs.ContentRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.INSPECT_BLOB),
        inspect=inspect,
    )
)

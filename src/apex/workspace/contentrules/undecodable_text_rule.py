"""Source that is not text.

Every input the build reads today is text, so opaque data must not arrive under a new name
without someone deciding to accept it.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import contentrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.blob-not-utf8")
ENCODING = "utf-8"


def inspect(subject: rulespecs.ContentSubject) -> Sequence[rulespecs.Finding]:
    try:
        subject.payload.decode(ENCODING)
    except UnicodeDecodeError:
        return (
            rulespecs.Finding(
                rule=RULE,
                reason=refusals.RefusalReason.REPOSITORY_BLOB_NOT_UTF8,
                subject=subject.path.value,
                remedy="binary source needs a reviewed packaging route",
            ),
        )
    return ()



contentrules.declare(
    rulespecs.ContentRule(
        id=RULE,
        origin=ruleorigins.Decomposed(ruleorigins.LegacySurface.INSPECT_BLOB),
        inspect=inspect,
    )
)

"""A file that names an external organisation.

The one permitted form is a package coordinate, where the name is part of an upstream package
identifier and points at that upstream rather than crediting anyone. Every other occurrence is
refused. The name is assembled rather than written out, because a rule carrying the literal
would refuse its own source file.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from apex.kernel import identifiers, refusals
from apex.workspace import contentrules, ruleorigins, rulespecs

RULE = identifiers.RuleId("repository.vendor-attribution")
VENDOR = b"goo" + b"gle"
PERMITTED_COORDINATE = VENDOR + b"-noto-sans-cjk-fonts"
OCCURRENCE = re.compile(re.escape(VENDOR), re.IGNORECASE)


def _outside_a_coordinate(payload: bytes) -> bool:
    stripped = payload.replace(PERMITTED_COORDINATE, b"")
    return OCCURRENCE.search(stripped) is not None


def inspect(subject: rulespecs.ContentSubject) -> Sequence[rulespecs.Finding]:
    if not _outside_a_coordinate(subject.payload):
        return ()
    return (
        rulespecs.Finding(
            rule=RULE,
            reason=refusals.RefusalReason.VENDOR_ATTRIBUTION_PRESENT,
            subject=subject.path.value,
            remedy="name what the thing does, not who else publishes one",
        ),
    )


contentrules.declare(
    rulespecs.ContentRule(
        id=RULE,
        origin=ruleorigins.Introduced(
            phase="P14",
            why=(
                "the style rules forbid naming an external organisation anywhere in the "
                "project, and the earlier guard has no rule about it at all"
            ),
        ),
        inspect=inspect,
    )
)

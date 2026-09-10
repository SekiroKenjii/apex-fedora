"""Where a rule came from, as a typed field on the rule itself.

The guard being replaced is a working control, so the decomposition has to be provably no
weaker. That proof needs to tell two things apart: a rule that transcribes an existing refusal,
which must agree with the old guard exactly in both directions, and a rule that adds a refusal
the old guard never made, which is allowed to refuse more and must say why.

Keeping the distinction on the rule removes the central list it would otherwise live in, so
adding a deliberate new refusal stays one new file.
"""

from __future__ import annotations

import dataclasses
import enum

from apex.kernel import errors


class LegacySurface(enum.StrEnum):
    PERMITTED = "permitted"
    INSPECT_BLOB = "inspect-blob"
    INSPECT_TREE = "inspect-tree"
    VALIDATE_SUBJECT = "validate-subject"
    INSPECT_OUTGOING = "inspect-outgoing"


@dataclasses.dataclass(frozen=True, slots=True)
class Decomposed:
    """Transcribes part of an existing refusal. Must agree in both directions."""

    surface: LegacySurface


@dataclasses.dataclass(frozen=True, slots=True)
class Introduced:
    """Refuses something the old guard permits. May only ever refuse more."""

    phase: str
    why: str

    def __post_init__(self) -> None:
        if not self.why.strip():
            raise errors.RegistrationError(
                f"{self.phase}: a rule that refuses more than the guard it replaces must say why"
            )


type RuleOrigin = Decomposed | Introduced

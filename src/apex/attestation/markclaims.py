"""What a reader claims about the mark, expressed as the key it registers under.

Absence is an ordinary key rather than a fallback branch, so exactly one unit may claim it and
a second claimant fails the seal instead of quietly shadowing the first.
"""

from __future__ import annotations

import dataclasses
import typing

from apex.model import storemark

ABSENT_KEY = "absent"
MARK_KEY_PREFIX = "mark"


@dataclasses.dataclass(frozen=True, slots=True)
class MarkAbsent:
    def key(self) -> str:
        return ABSENT_KEY


@dataclasses.dataclass(frozen=True, slots=True)
class MarkEquals:
    value: int

    def key(self) -> str:
        return f"{MARK_KEY_PREFIX}:{self.value}"


type MarkClaim = MarkAbsent | MarkEquals


def key_for(mark: storemark.Unmarked | storemark.Marked) -> str:
    """The one exhaustive dispatch over a readable mark. Election does not repeat it."""
    if isinstance(mark, storemark.Unmarked):
        return MarkAbsent().key()
    if isinstance(mark, storemark.Marked):
        return MarkEquals(mark.version).key()
    typing.assert_never(mark)

"""Wall time, for annotating a record with when it happened.

Kept apart from the monotonic clock on purpose. Ordering in the ledger comes from the
sequence number, never from a timestamp, so a clock that jumps cannot reorder evidence.
"""

from __future__ import annotations

import dataclasses
from typing import Protocol

from apex.kernel import claims


@dataclasses.dataclass(frozen=True, slots=True)
class Stamp:
    rendered: str


class WallClockPort(Protocol):
    environment: claims.EnvironmentKind

    def stamp(self) -> Stamp: ...

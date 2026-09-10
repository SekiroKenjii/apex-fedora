"""A wall clock that does not move, so a rendered record is byte reproducible."""

from __future__ import annotations

from apex.kernel import claims
from apex.ports import wallclock

FROZEN = "2026-01-01T00:00:00+00:00"


class FixedWallClock:
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self, rendered: str = FROZEN) -> None:
        self._rendered = rendered

    def stamp(self) -> wallclock.Stamp:
        return wallclock.Stamp(self._rendered)

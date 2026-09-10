"""The system wall clock, rendered the way the stored records already render it."""

from __future__ import annotations

import datetime

from apex.kernel import claims
from apex.ports import wallclock


class SystemWallClock:
    environment = claims.EnvironmentKind.BUILD

    def stamp(self) -> wallclock.Stamp:
        return wallclock.Stamp(datetime.datetime.now(datetime.UTC).isoformat())

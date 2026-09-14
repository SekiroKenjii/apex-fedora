"""A clock the test advances, so no test ever waits.

The stamp is a fixed epoch moved forward by however far the test has advanced the clock,
so a rendered record is byte reproducible and still changes when time is made to pass.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable

from apex.kernel import claims, timing
from apex.ports import clock

EPOCH = timing.Instant(0)
FIXED_ORIGIN = datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)


class ManualClock(clock.ClockPort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self, start: timing.Instant = EPOCH) -> None:
        self._now = start
        self.slept: list[timing.Elapsed] = []

    def now(self) -> timing.Instant:
        return self._now

    def stamp(self) -> clock.Stamp:
        moment = FIXED_ORIGIN + datetime.timedelta(seconds=self._now.seconds)
        return clock.Stamp(moment.isoformat())

    def advance(self, span: timing.Elapsed) -> None:
        self._now = timing.Instant(self._now.seconds + span.seconds)

    def sleep(self, span: timing.Elapsed) -> None:
        self.slept.append(span)
        self.advance(span)

    def wait_until(
        self, condition: Callable[[], bool], policy: timing.WaitPolicy
    ) -> timing.Elapsed:
        return clock.wait(self.now, self.sleep, condition, policy)

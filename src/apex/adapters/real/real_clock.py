"""The system clock, with one polling loop for the whole project."""

from __future__ import annotations

import datetime
import time
from collections.abc import Callable

from apex.kernel import claims, timing
from apex.ports import clock


class SystemClock(clock.ClockPort):
    environment = claims.EnvironmentKind.BUILD

    def now(self) -> timing.Instant:
        return timing.Instant(time.monotonic())

    def stamp(self) -> clock.Stamp:
        return clock.Stamp(datetime.datetime.now(datetime.UTC).isoformat())

    def sleep(self, span: timing.Elapsed) -> None:
        time.sleep(span.seconds)

    def wait_until(
        self, condition: Callable[[], bool], policy: timing.WaitPolicy
    ) -> timing.Elapsed:
        return clock.wait(self.now, self.sleep, condition, policy)

"""Time, injected.

Because the clock is a port, a 240 second budget elapses in microseconds in the fast suite,
and a timeout is asserted exactly rather than by feeding a hand-built sequence of numbers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from apex.kernel import claims, timing


class ClockPort(Protocol):
    environment: claims.EnvironmentKind

    def now(self) -> timing.Instant: ...

    def sleep(self, span: timing.Elapsed) -> None: ...

    def wait_until(
        self, condition: Callable[[], bool], policy: timing.WaitPolicy
    ) -> timing.Elapsed: ...

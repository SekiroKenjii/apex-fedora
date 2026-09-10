"""The system clock, with one polling loop for the whole project."""

from __future__ import annotations

import time
from collections.abc import Callable

from apex.kernel import claims, errors, timing


class SystemClock:
    environment = claims.EnvironmentKind.BUILD

    def now(self) -> timing.Instant:
        return timing.Instant(time.monotonic())

    def sleep(self, span: timing.Elapsed) -> None:
        time.sleep(span.seconds)

    def wait_until(
        self, condition: Callable[[], bool], policy: timing.WaitPolicy
    ) -> timing.Elapsed:
        started = self.now()
        attempt = 0
        while True:
            if condition():
                return timing.Elapsed(self.now().seconds - started.seconds)
            deadline = timing.Deadline(policy.deadline.budget, started=started)
            if deadline.expired_at(self.now()):
                raise errors.PortFailure(
                    port="clock",
                    cause=f"waited {policy.deadline.budget.seconds}s for {policy.description}",
                )
            self.sleep(policy.backoff.delay(attempt))
            attempt += 1

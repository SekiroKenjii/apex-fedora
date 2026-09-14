"""Time, injected.

Because the clock is a port, a 240 second budget elapses in microseconds in the fast suite,
and a timeout is asserted exactly rather than by feeding a hand-built sequence of numbers.

Two readings live here and answer different questions. `now` is monotonic and measures
waiting; it cannot name a moment. `stamp` is wall time rendered for a record; nothing that
decides anything reads it, and ordering in the ledger comes from the sequence number, so a
clock that jumps cannot reorder evidence.
"""

from __future__ import annotations

import dataclasses
from abc import abstractmethod
from collections.abc import Callable
from typing import Protocol

from apex.kernel import claims, errors, timing


@dataclasses.dataclass(frozen=True, slots=True)
class Stamp:
    rendered: str


class ClockPort(Protocol):
    environment: claims.EnvironmentKind

    @abstractmethod
    def now(self) -> timing.Instant: ...

    @abstractmethod
    def stamp(self) -> Stamp: ...

    @abstractmethod
    def sleep(self, span: timing.Elapsed) -> None: ...

    @abstractmethod
    def wait_until(
        self, condition: Callable[[], bool], policy: timing.WaitPolicy
    ) -> timing.Elapsed: ...


def wait(
    now: Callable[[], timing.Instant],
    sleep: Callable[[timing.Elapsed], None],
    condition: Callable[[], bool],
    policy: timing.WaitPolicy,
) -> timing.Elapsed:
    """Poll under the policy's backoff until the condition holds or its deadline passes."""
    started = now()
    attempt = 0
    while True:
        if condition():
            return timing.Elapsed(now().seconds - started.seconds)
        deadline = timing.Deadline(policy.deadline.budget, started=started)
        if deadline.expired_at(now()):
            raise errors.PortFailure(
                port="clock",
                cause=f"waited {policy.deadline.budget.seconds}s for {policy.description}",
            )
        sleep(policy.backoff.delay(attempt))
        attempt += 1

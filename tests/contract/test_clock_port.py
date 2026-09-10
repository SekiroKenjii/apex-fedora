"""Waiting for a real condition, with a bounded budget."""

from __future__ import annotations

import pytest

from apex.kernel import errors, timing
from apex.ports import clock as clock_port


def policy(budget: float, description: str = "the condition holds") -> timing.WaitPolicy:
    return timing.WaitPolicy(
        deadline=timing.Deadline(timing.Elapsed(budget)),
        backoff=timing.Backoff.exponential(
            first=timing.Elapsed(0.001), ceiling=timing.Elapsed(0.01), factor=2
        ),
        description=description,
    )


def test_a_condition_that_already_holds_returns_at_once(clocks: clock_port.ClockPort) -> None:
    assert clocks.wait_until(lambda: True, policy(1)).seconds >= 0


def test_a_condition_that_becomes_true_is_awaited(clocks: clock_port.ClockPort) -> None:
    remaining = [3]

    def ready() -> bool:
        remaining[0] -= 1
        return remaining[0] <= 0

    clocks.wait_until(ready, policy(5))

    assert remaining[0] <= 0


def test_a_condition_that_never_holds_raises_a_port_failure(
    clocks: clock_port.ClockPort,
) -> None:
    with pytest.raises(errors.PortFailure) as raised:
        clocks.wait_until(lambda: False, policy(0.05, "the guest answers"))

    assert "the guest answers" in str(raised.value)


def test_time_advances_when_the_clock_sleeps(clocks: clock_port.ClockPort) -> None:
    before = clocks.now()

    clocks.sleep(timing.Elapsed(0.01))

    assert clocks.now().seconds >= before.seconds

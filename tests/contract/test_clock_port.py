"""Waiting for a real condition with a bounded budget, and stamping a record with wall time.

`now` is monotonic and measures waiting. `stamp` is wall time rendered for a record. They
sit on one port because a stage that has a clock has both, and nothing that decides anything
reads the stamp: ordering in the ledger comes from the sequence number.
"""

from __future__ import annotations

import re

import pytest

from apex.adapters.fakes import fake_clock
from apex.kernel import errors, timing
from apex.ports import clock as clock_port

ISO_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00")


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


def test_a_condition_that_never_holds_raises_a_port_failure(clocks: clock_port.ClockPort) -> None:
    with pytest.raises(errors.PortFailure) as raised:
        clocks.wait_until(lambda: False, policy(0.05, "the guest answers"))

    assert "the guest answers" in str(raised.value)


def test_time_advances_when_the_clock_sleeps(clocks: clock_port.ClockPort) -> None:
    before = clocks.now()

    clocks.sleep(timing.Elapsed(0.01))

    assert clocks.now().seconds >= before.seconds


def test_a_stamp_is_an_iso_instant_in_utc(clocks: clock_port.ClockPort) -> None:
    assert ISO_INSTANT.fullmatch(clocks.stamp().rendered)


def test_a_stamp_matches_the_shape_the_stored_records_already_use(
    clocks: clock_port.ClockPort,
) -> None:
    """The v1 records carry `2026-09-08T14:29:48.549782+00:00`."""
    assert clocks.stamp().rendered.endswith("+00:00")


def test_stamps_do_not_move_backwards(clocks: clock_port.ClockPort) -> None:
    first = clocks.stamp()
    clocks.sleep(timing.Elapsed(0.01))
    second = clocks.stamp()

    assert second.rendered >= first.rendered


def test_the_fake_stamp_is_reproducible_and_follows_the_manual_clock() -> None:
    one = fake_clock.ManualClock()
    other = fake_clock.ManualClock()

    assert one.stamp().rendered == other.stamp().rendered

    one.advance(timing.Elapsed(90))

    assert one.stamp().rendered > other.stamp().rendered

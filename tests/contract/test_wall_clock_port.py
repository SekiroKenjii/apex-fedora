"""Two clocks, because they answer different questions.

`ClockPort.now` is monotonic and measures waiting. It cannot produce a `recorded_at`, and a
monotonic reading written into a record as a timestamp would be meaningless the next boot.
"""

from __future__ import annotations

import re

from apex.ports import wallclock as wallclock_port

ISO_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?\+00:00")


def test_a_stamp_is_an_iso_instant_in_utc(wall_clocks: wallclock_port.WallClockPort) -> None:
    assert ISO_INSTANT.fullmatch(wall_clocks.stamp().rendered)


def test_a_stamp_matches_the_shape_the_stored_records_already_use(
    wall_clocks: wallclock_port.WallClockPort,
) -> None:
    """The v1 records carry `2026-09-08T14:29:48.549782+00:00`."""
    assert wall_clocks.stamp().rendered.endswith("+00:00")


def test_stamps_do_not_move_backwards(wall_clocks: wallclock_port.WallClockPort) -> None:
    first = wall_clocks.stamp()
    second = wall_clocks.stamp()

    assert second.rendered >= first.rendered


def test_the_fake_is_deterministic() -> None:
    from apex.adapters.fakes import fake_wallclock

    clock = fake_wallclock.FixedWallClock()

    assert clock.stamp().rendered == fake_wallclock.FixedWallClock().stamp().rendered

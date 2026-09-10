"""The installed console script must not change what any command prints."""

from __future__ import annotations

from pathlib import Path

import pytest

from migration import entry_point_parity


def test_the_parity_check_covers_most_of_the_corpus() -> None:
    assert len(entry_point_parity.invocation_arguments()) >= 60


@pytest.mark.golden
def test_both_entry_points_agree_on_every_invocation(tmp_path: Path) -> None:
    assert entry_point_parity.compare(tmp_path) == []

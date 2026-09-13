"""The installed console script must not change what any command prints."""

from __future__ import annotations

from pathlib import Path

import pytest

from migration import entry_point_parity


def test_the_parity_check_covers_every_invocation_the_bridge_still_answers() -> None:
    from apex.cli import legacy_bridge
    from migration import golden_corpus

    covered = entry_point_parity.invocation_arguments()
    bridged = [
        invocation
        for invocation in golden_corpus.invocations()
        if "<subject>" not in invocation.arguments
        and (not invocation.arguments or legacy_bridge.handles(invocation.arguments[0]))
    ]

    assert len(covered) == len(bridged) >= 2


@pytest.mark.golden
def test_both_entry_points_agree_on_every_invocation(tmp_path: Path) -> None:
    assert entry_point_parity.compare(tmp_path) == []

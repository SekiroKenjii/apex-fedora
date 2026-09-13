"""Every hook Git runs is answered by the rules, and nothing older stands behind them.

Two lists of hook kinds once existed: the one the older entry point accepted and the one the
rules registered. The older entry point is gone, so the only list is the registry's, and the
installed hooks may name nothing outside it.
"""

from __future__ import annotations

from pathlib import Path

from apex.cli import hookinstall, hookkinds

ROOT = Path(__file__).resolve().parents[2]
DECIDED = ("commit-msg", "pre-commit", "pre-push")


def test_the_three_hooks_git_runs_are_the_kinds_the_rules_answer() -> None:
    assert hookkinds.names() == DECIDED


def test_each_installed_hook_hands_its_own_kind_to_the_entry_point_and_nothing_else() -> None:
    for kind in DECIDED:
        lines = hookinstall.body(kind).splitlines()

        assert len(lines) == 3
        assert lines[2].endswith(f'git-hook {kind} "$@"')
        assert "tools/apex.py" not in hookinstall.body(kind)


def test_no_forwarder_and_no_older_entry_point_remain() -> None:
    assert not (ROOT / "tools" / "apex.py").exists()
    assert not (ROOT / "tools" / "bootstrap.py").exists()
    assert not (ROOT / "tools" / "apexlib" / "guardforward.py").exists()

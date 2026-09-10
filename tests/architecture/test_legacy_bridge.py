"""The bridge into the old tools tree may only ever shrink."""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

from apex.cli import legacy_bridge

REPOSITORY = Path(__file__).resolve().parents[2]
BRIDGE_PATH = "src/apex/cli/legacy_bridge.py"


def _literal_names(node: ast.expr) -> frozenset[str]:
    """Read a set literal, including one wrapped in a `frozenset(...)` call."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id != "frozenset" or len(node.args) != 1:
            raise ValueError("BRIDGED must be a set literal or a frozenset of one")
        node = node.args[0]
    return frozenset(ast.literal_eval(node))


def bridged_at(revision: str) -> frozenset[str] | None:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{BRIDGE_PATH}"],
        capture_output=True, text=True, cwd=REPOSITORY,
    )
    if completed.returncode != 0:
        return None
    tree = ast.parse(completed.stdout)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "BRIDGED" for target in node.targets
        ):
            return _literal_names(node.value)
    return None


def test_the_bridge_covers_every_subcommand_the_corpus_exercises() -> None:
    from migration import golden_corpus

    assert set(golden_corpus.SUBCOMMANDS) == set(legacy_bridge.BRIDGED)


def test_the_bridge_never_grows() -> None:
    previous = bridged_at("HEAD")
    if previous is None:
        pytest.skip("NOT TESTED: the bridge is not committed yet")

    assert previous >= legacy_bridge.BRIDGED


def test_the_bridge_answers_only_for_names_it_holds() -> None:
    assert legacy_bridge.handles("doctor")
    assert not legacy_bridge.handles("no-such-command")


def test_the_legacy_entry_point_still_exists() -> None:
    assert legacy_bridge.LEGACY_ENTRY_POINT.is_file()


def test_the_declared_version_matches_the_distribution() -> None:
    import tomllib

    import apex

    document = tomllib.loads((REPOSITORY / "pyproject.toml").read_text())

    assert document["project"]["version"] == apex.__version__

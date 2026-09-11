"""Which hooks the rules answer, and the property that keeps a fault from deciding a commit.

Two lists of hook kinds exist: the one the entry point accepts as argparse choices, and the one
the rules register. A kind in the registry that the entry point rejects can never be reached, and
a kind the entry point accepts that no guard decides would be a hook that permits everything.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from apex.cli import hookkinds

ROOT = Path(__file__).resolve().parents[2]
ENTRY = ROOT / "tools" / "bootstrap.py"
FORWARDER = ROOT / "tools" / "apexlib" / "guardforward.py"
DECIDED = frozenset({"pre-commit", "commit-msg", "pre-push"})
CHOICES = re.compile(r"hook\.add_argument\(\s*[\"']kind[\"'],\s*choices=(\[[^\]]*\])")


def accepted() -> frozenset[str]:
    found = CHOICES.search(ENTRY.read_text())
    assert found, "the git-hook parser no longer declares its choices in one literal"
    return frozenset(ast.literal_eval(found.group(1)))


def test_every_transferred_kind_is_one_the_entry_point_accepts() -> None:
    assert frozenset(hookkinds.names()) <= accepted()


def test_no_kind_is_unreachable_by_either_guard() -> None:
    assert accepted() == DECIDED


def test_the_forwarder_never_lets_a_fault_decide_the_commit() -> None:
    """A commit must not become permitted because the new code went wrong.

    The forwarder therefore catches everything, reports it, and asks the previous guard anyway.
    Two returns: the verdict from the rules, and the verdict from the guard behind them.
    """
    if not FORWARDER.is_file():
        return
    source = FORWARDER.read_text()
    tree = ast.parse(source, filename=str(FORWARDER))
    run = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "run"
    )

    assert "except BaseException:" in source
    assert "_legacy(" in source
    assert sum(1 for node in ast.walk(run) if isinstance(node, ast.Return)) == 2

"""Size is a decision, so growth past a budget is a failing test rather than a surprise.

The budgets are numbers somebody chose, written where a reviewer can see them change. A
package that needs more room gets it in the same change that explains why, not by drifting.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "src" / "apex"
MODULE_LINE_LIMIT = 400
FAN_IN_LIMIT = 40
# The kernel is the shared vocabulary, `config.defaults` is the one place a number lives,
# `ports.portset` is the bundle every host stage names in its signature, `pipeline.stages` is
# the stage vocabulary every stage is made of, `composition.keys` is the fact vocabulary the
# build stages pass to one another, and `ports.guestshell` is the port every stage that asks
# a guest names; the specification makes all six central on purpose, so none is a hidden hub.
FAN_IN_EXEMPT = (
    "apex.kernel", "apex.config.defaults", "apex.ports.portset", "apex.pipeline.stages",
    "apex.composition.keys", "apex.ports.guestshell",
)
PACKAGE_LINE_BUDGETS = {
    "kernel": 1500,
    "assets": 100,
    "model": 1800,
    "ports": 1100,
    "registry": 700,
    "pipeline": 1200,
    "config": 700,
    "targeting": 600,
    "attestation": 3600,
    "composition": 2400,
    "verification": 6400,
    "generating": 800,
    "provisioning": 2400,
    "trust": 1200,
    "agent": 5600,
    "workspace": 2000,
    "adapters": 3100,
    "cli": 3300,
    "wiring": 300,
}


def line_count(path: Path) -> int:
    return len(path.read_text().splitlines())


def test_no_module_exceeds_the_line_limit() -> None:
    oversized = [
        f"{path.relative_to(SOURCE)}: {line_count(path)}"
        for path in sorted(SOURCE.rglob("*.py"))
        if line_count(path) > MODULE_LINE_LIMIT
    ]

    assert oversized == []


@pytest.mark.parametrize("package,budget", sorted(PACKAGE_LINE_BUDGETS.items()))
def test_each_package_stays_within_its_line_budget(package: str, budget: int) -> None:
    directory = SOURCE / package
    if not directory.is_dir():
        pytest.skip(f"NOT TESTED: {package} is not built yet")
    total = sum(line_count(path) for path in directory.rglob("*.py"))

    assert total <= budget, f"{package} is {total} lines against a budget of {budget}"


def importers_by_module() -> dict[str, int]:
    counted: dict[str, int] = {}
    for path in SOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("apex"):
                for alias in node.names:
                    target = (
                        f"{node.module}.{alias.name}"
                        if alias.name[0].islower()
                        else node.module
                    )
                    counted[target] = counted.get(target, 0) + 1
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("apex"):
                        counted[alias.name] = counted.get(alias.name, 0) + 1
    return counted


def test_no_module_outside_the_kernel_is_imported_by_more_than_the_fan_in_limit() -> None:
    """The kernel and the defaults are expected to be everywhere. Nothing else is."""
    crowded = [
        f"{module}: {count}"
        for module, count in sorted(importers_by_module().items())
        if count > FAN_IN_LIMIT and not module.startswith(FAN_IN_EXEMPT)
    ]

    assert crowded == []


def test_every_package_that_exists_has_a_budget() -> None:
    present = {
        path.name
        for path in SOURCE.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }

    assert present <= set(PACKAGE_LINE_BUDGETS)

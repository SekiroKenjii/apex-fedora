"""Size is a decision, so growth past a budget is a failing test rather than a surprise.

The budgets are numbers somebody chose, written where a reviewer can see them change. A
package that needs more room gets it in the same change that explains why, not by drifting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "src" / "apex"
MODULE_LINE_LIMIT = 400
PACKAGE_LINE_BUDGETS = {
    "kernel": 1400,
    "model": 1200,
    "ports": 800,
    "registry": 700,
    "pipeline": 1200,
    "config": 600,
    "targeting": 600,
    "attestation": 3600,
    "workspace": 2000,
    "adapters": 1600,
    "cli": 900,
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


def test_every_package_that_exists_has_a_budget() -> None:
    present = {
        path.name
        for path in SOURCE.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }

    assert present <= set(PACKAGE_LINE_BUDGETS)

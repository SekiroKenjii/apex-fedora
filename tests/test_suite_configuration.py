"""Keep 'green' honest.

A suite that collects opt-in cases and reports them as skipped reads as success while
proving nothing. These assertions fix what the default run covers, so widening it is a
deliberate edit rather than a drift.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
# 6 added in P4 that read the real evidence store, and 4 added in P11 that read it again
# through the versioned reader; the inherited guest cases left with the older host tools.
EXPECTED_INTEGRATION_CASES = 10


def options() -> dict[str, object]:
    document = tomllib.loads((REPOSITORY / "pyproject.toml").read_text())
    return document["tool"]["pytest"]["ini_options"]


def test_opt_in_markers_are_deselected_by_default() -> None:
    addopts = str(options()["addopts"])

    assert "not integration" in addopts
    assert "not benchmark" in addopts


def test_every_marker_used_in_the_suite_is_declared() -> None:
    declared = {str(entry).split(":", 1)[0] for entry in options()["markers"]}
    used = set()
    for path in (REPOSITORY / "tests").rglob("test_*.py"):
        for line in path.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("@pytest.mark."):
                used.add(stripped.removeprefix("@pytest.mark.").split("(")[0])

    assert used - {"parametrize", "skip", "skipif", "xfail", "usefixtures"} <= declared


def test_the_number_of_opt_in_cases_is_fixed() -> None:
    integration = sum(
        line.strip().startswith("def test_")
        for path in (REPOSITORY / "tests" / "integration").glob("test_*.py")
        for line in path.read_text().splitlines()
    )

    assert integration == EXPECTED_INTEGRATION_CASES

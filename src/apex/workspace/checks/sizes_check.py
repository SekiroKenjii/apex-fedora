"""The sizes the architecture is held to, measured and reported as a table.

The architecture tests refuse the same limits; this check says the numbers, package by
package, so the report the acceptance asks for is one command away.
"""

from __future__ import annotations

from pathlib import Path

from apex.config import budgets, toolchain
from apex.workspace import checks


def lines_of(path: Path) -> int:
    return len(path.read_text().splitlines())


def measure(package_root: Path) -> tuple[dict[str, int], list[str]]:
    """Each package's line total, and every module over the module limit."""
    totals: dict[str, int] = {}
    oversize: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        relative = path.relative_to(package_root)
        if len(relative.parts) == 1 and relative.stem.startswith("__"):
            continue
        package = relative.parts[0] if len(relative.parts) > 1 else relative.stem
        count = lines_of(path)
        totals[package] = totals.get(package, 0) + count
        if count > budgets.MODULE_LINE_LIMIT:
            oversize.append(f"{relative}: {count} lines")
    return totals, oversize


def run(site: checks.Site) -> checks.Outcome:
    totals, oversize = measure(site.repository / toolchain.PACKAGE)
    rows = [
        f"{package:<14}{total:>7}{budgets.PACKAGE_LINE_BUDGETS.get(package, 0):>7}"
        for package, total in sorted(totals.items())
    ]
    over = [
        f"{package}: {total} lines against a budget of {budgets.PACKAGE_LINE_BUDGETS[package]}"
        for package, total in sorted(totals.items())
        if package in budgets.PACKAGE_LINE_BUDGETS and total > budgets.PACKAGE_LINE_BUDGETS[package]
    ]
    unbudgeted = [package for package in totals if package not in budgets.PACKAGE_LINE_BUDGETS]
    problems = [*oversize, *over, *(f"{package}: no budget declared" for package in unbudgeted)]
    detail = "\n".join([f"{'package':<14}{'lines':>7}{'budget':>7}", *rows, *problems])
    return checks.Outcome(status=checks.FAIL if problems else checks.PASS, detail=detail)


checks.declare(
    checks.Check(
        id="sizes",
        summary="no module is over the line limit and no package over its budget",
        order=100,
        run=run,
    )
)

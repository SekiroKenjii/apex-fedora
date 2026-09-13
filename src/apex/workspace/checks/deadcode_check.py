"""Vulture over the package, the migration tools and every restructured test tree."""

from __future__ import annotations

from apex.config import toolchain
from apex.workspace import checks


def run(site: checks.Site) -> checks.Outcome:
    return checks.program(
        site,
        (
            *toolchain.uv(site.python, "vulture"),
            "vulture",
            *toolchain.DEAD_CODE_TREES,
            "--min-confidence",
            toolchain.DEAD_CODE_CONFIDENCE,
        ),
    )


checks.declare(
    checks.Check(
        id="deadcode", summary="vulture finds no unused code at its confidence", order=50, run=run
    )
)

"""Ruff's rules, as `pyproject.toml` selects them, over every governed tree."""

from __future__ import annotations

from apex.config import toolchain
from apex.workspace import checks


def run(site: checks.Site) -> checks.Outcome:
    return checks.program(
        site,
        (
            *toolchain.uv(site.python, "ruff"),
            "ruff",
            "check",
            "--no-cache",
            *toolchain.SOURCE_TREES,
            *toolchain.TEST_TREES,
        ),
    )


checks.declare(
    checks.Check(id="lint", summary="ruff finds no violation of a selected rule", order=20, run=run)
)

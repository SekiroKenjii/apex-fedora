"""The formatter in check mode over every tree the style document governs."""

from __future__ import annotations

from apex.config import toolchain
from apex.workspace import checks


def run(site: checks.Site) -> checks.Outcome:
    return checks.program(
        site,
        (
            *toolchain.uv(site.python, "ruff"),
            "ruff",
            "format",
            "--check",
            *toolchain.SOURCE_TREES,
            *toolchain.TEST_TREES,
        ),
    )


checks.declare(
    checks.Check(
        id="format", summary="the ruff formatter finds nothing to change", order=10, run=run
    )
)

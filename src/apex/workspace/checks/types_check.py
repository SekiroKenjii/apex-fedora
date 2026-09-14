"""Strict mypy over the package."""

from __future__ import annotations

from apex.config import toolchain
from apex.workspace import checks


def run(site: checks.Site) -> checks.Outcome:
    return checks.program(
        site, (*toolchain.uv(site.python, "mypy"), "mypy", "--strict", toolchain.PACKAGE)
    )


checks.declare(checks.Check(id="types", summary="mypy --strict finds no error", order=30, run=run))

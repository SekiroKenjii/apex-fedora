"""Pyright over the package and the typed tests, resolving against the tool environment."""

from __future__ import annotations

from apex.config import toolchain
from apex.workspace import checks

PYRIGHT = 'pyright --pythonpath "$(command -v python)"'


def run(site: checks.Site) -> checks.Outcome:
    return checks.program(
        site, (*toolchain.uv(site.python, "pytest", "pyright"), "sh", "-c", PYRIGHT)
    )


checks.declare(checks.Check(id="pyright", summary="pyright finds no error", order=40, run=run))

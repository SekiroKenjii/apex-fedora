"""Pylint's duplicate-code rule over the package, at the similarity `pyproject.toml` sets."""

from __future__ import annotations

from apex.config import toolchain
from apex.workspace import checks


def run(site: checks.Site) -> checks.Outcome:
    return checks.program(
        site,
        (
            *toolchain.uv(site.python, "pylint"),
            "pylint",
            "--disable=all",
            f"--enable={toolchain.DUPLICATE_RULE}",
            toolchain.PACKAGE,
        ),
    )


checks.declare(
    checks.Check(
        id="duplicates",
        summary="pylint finds no block of similar lines in two modules",
        order=60,
        run=run,
    )
)

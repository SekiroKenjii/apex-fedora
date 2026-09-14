"""The import linter's contracts over the package: the layers, downward only."""

from __future__ import annotations

from apex.config import toolchain
from apex.workspace import checks


def run(site: checks.Site) -> checks.Outcome:
    return checks.program(
        site,
        (*toolchain.uv(site.python, "import-linter"), "lint-imports"),
        variables={"PYTHONPATH": toolchain.SOURCE_TREES[0]},
    )


checks.declare(
    checks.Check(
        id="imports", summary="the import linter's layer contract holds", order=70, run=run
    )
)

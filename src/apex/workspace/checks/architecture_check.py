"""The architecture tests: every rule of the style document that a test holds."""

from __future__ import annotations

from apex.config import toolchain
from apex.workspace import checks


def run(site: checks.Site) -> checks.Outcome:
    return checks.program(
        site, (*toolchain.uv(site.python, "pytest"), "pytest", "-q", toolchain.ARCHITECTURE_TESTS)
    )


checks.declare(
    checks.Check(id="architecture", summary="every architecture test passes", order=80, run=run)
)

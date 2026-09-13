"""The pinned tools every check runs, one version each, and the trees they run over.

A check names a tool by name and gets the pinned release through uv, so the gate on every
machine runs the same program; the justfile renders the same pins. The interpreter is the
one the command itself runs under, which the justfile chose.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping

PYTHON = "3.14.4"
PINS: Mapping[str, str] = {
    "ruff": "0.14.5",
    "mypy": "1.18.2",
    "pyright": "1.1.407",
    "vulture": "2.14",
    "pytest": "9.1.1",
    "pylint": "4.0.8",
    "import-linter": "2.15",
}
PACKAGE = "src/apex"
SOURCE_TREES: tuple[str, ...] = ("src", "tools/migration")
TEST_TREES: tuple[str, ...] = (
    "tests/unit",
    "tests/pipelines",
    "tests/architecture",
    "tests/contract",
    "tests/property",
    "tests/support",
)
DEAD_CODE_TREES: tuple[str, ...] = (PACKAGE, "tools/migration", *TEST_TREES, "tests/integration")
ARCHITECTURE_TESTS = "tests/architecture"
DEAD_CODE_CONFIDENCE = "80"
DUPLICATE_RULE = "R0801"


def pin(name: str) -> str:
    return f"{name}=={PINS[name]}"


def running_python() -> str:
    """The interpreter this process runs under, as uv names a version."""
    return ".".join(str(part) for part in sys.version_info[:3])


def uv(python: str, *tools: str) -> tuple[str, ...]:
    """The uv invocation that runs the pinned tools under the named interpreter."""
    withs = tuple(word for name in tools for word in ("--with", pin(name)))
    return ("uv", "run", "--no-project", "--python", python, *withs)

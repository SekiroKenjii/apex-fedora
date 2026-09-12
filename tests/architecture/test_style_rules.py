"""The rules in docs/STYLE.md that a test can hold.

Each test names the rule it holds. A rule that is only a preference is not here, and a rule
here that fails is fixed in the code, not relaxed in the test.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from collections.abc import Iterator
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
SOURCE = REPOSITORY / "src" / "apex"
LAYERS = {
    "kernel": 0, "model": 1, "ports": 2, "registry": 3, "pipeline": 4,
    "config": 5, "targeting": 5,
    "attestation": 6, "workspace": 6, "trust": 6, "provisioning": 6, "composition": 6,
    "verification": 6,
    "adapters": 7, "wiring": 8, "cli": 9, "agent": 10,
}

# Phrases that only ever compare the tree with the code it replaced. Their history belongs in
# docs/MIGRATION.md, where it carries a date.
NARRATION = (
    "the current ",
    "currently",
    "today",
    "call sites",
    "written out in",
    "reimplementations",
    "hand-typed",
)

# A type may be imported by name only where a field of the importing module's class would
# shadow the type's module. Each entry is the field that forces it.
NAME_IMPORT_EXCEPTIONS = {
    "attestation/readiness.py": {"Verdict", "NotTested", "BLOCKED", "PASSED"},
    "pipeline/plans.py": {"FactKey", "Stage"},
    "pipeline/runner.py": {"FactKey", "FactMap"},
    "pipeline/stages.py": {"FactKey", "FactMap"},
}
TYPING_MODULES = ("typing", "collections.abc")

VERSION_LITERAL = re.compile(r"\bfc\d+\b|\bfedora-?\d+\b|\bGNOME ?\d+\b|\bgnome-\d+\b")
VERSION_HOMES = ("targeting/releases/",)

KIND_SUFFIXES = {
    "composition/stages": "_stage",
    "composition/recipes": "_recipe",
    "trust/negatives": "_negative",
    "workspace/entryrules": "_rule",
    "workspace/contentrules": "_rule",
    "workspace/messagerules": "_rule",
    "cli/hookkinds": "_hook",
    "attestation/storereaders": "_reader",
    "targeting/releases": "_release",
}

COMMENT_BUDGET = 40
RENDERING_MODULE = "cli/rendering.py"


def modules() -> Iterator[tuple[Path, ast.Module]]:
    for path in sorted(SOURCE.rglob("*.py")):
        yield path, ast.parse(path.read_text(), filename=str(path))


def relative(path: Path) -> str:
    return str(path.relative_to(SOURCE))


def docstrings(tree: ast.Module) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            text = ast.get_docstring(node)
            if text:
                yield text


def comments(path: Path) -> Iterator[str]:
    for token in tokenize.generate_tokens(io.StringIO(path.read_text()).readline):
        if token.type == tokenize.COMMENT and not token.string.startswith("#!"):
            yield token.string


def test_every_module_has_a_docstring() -> None:
    missing = [relative(path) for path, tree in modules() if ast.get_docstring(tree) is None]

    assert missing == []


def test_docstrings_and_comments_describe_the_tree_as_it_is() -> None:
    offenders = []
    for path, tree in modules():
        for text in (*docstrings(tree), *comments(path)):
            lowered = " ".join(text.lower().split())
            for phrase in NARRATION:
                if phrase in lowered:
                    offenders.append(f"{relative(path)}: {phrase!r}")

    assert offenders == []


def test_module_basenames_are_unique_within_a_layer() -> None:
    seen: dict[tuple[int, str], str] = {}
    duplicates = []
    for path, _ in modules():
        if path.name == "__init__.py":
            continue
        package = relative(path).split("/")[0]
        layer = LAYERS.get(package)
        if layer is None:
            continue
        key = (layer, path.name)
        if key in seen:
            duplicates.append(f"{seen[key]} and {relative(path)}")
        seen[key] = relative(path)

    assert duplicates == []


def test_name_imports_are_limited_to_the_declared_exceptions() -> None:
    offenders = []
    for path, tree in modules():
        allowed = NAME_IMPORT_EXCEPTIONS.get(relative(path), set())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if node.module in TYPING_MODULES or node.module == "__future__":
                continue
            if not node.module.startswith("apex."):
                continue
            for alias in node.names:
                if alias.name[0].isupper() and alias.name not in allowed:
                    offenders.append(f"{relative(path)} imports {alias.name} from {node.module}")

    assert offenders == []


def test_version_literals_live_only_in_targeting_and_pins() -> None:
    offenders = []
    for path, _ in modules():
        if relative(path).startswith(VERSION_HOMES):
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if VERSION_LITERAL.search(line):
                offenders.append(f"{relative(path)}:{number}")

    assert offenders == []


@pytest.mark.parametrize("package,suffix", sorted(KIND_SUFFIXES.items()))
def test_registered_units_carry_their_kind_as_a_suffix(package: str, suffix: str) -> None:
    directory = SOURCE / package
    if not directory.is_dir():
        pytest.skip(f"NOT TESTED: {package} is not built yet")
    offenders = [
        path.name
        for path in directory.rglob("*.py")
        if not path.name.startswith("_") and not path.stem.endswith(suffix)
    ]

    assert offenders == []


def test_print_is_confined_to_rendering() -> None:
    offenders = [
        f"{relative(path)}:{node.lineno}"
        for path, tree in modules()
        if relative(path) != RENDERING_MODULE
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "print"
    ]

    assert offenders == []


def test_comment_lines_stay_within_the_budget() -> None:
    counted = sum(
        1
        for path, _ in modules()
        for text in comments(path)
        if not text.startswith(("# noqa", "# type:"))
    )

    assert counted <= COMMENT_BUDGET


def test_the_style_document_names_every_test_here() -> None:
    document = (REPOSITORY / "docs" / "STYLE.md").read_text()
    names = [
        node.name
        for node in ast.parse(Path(__file__).read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
        and node.name != "test_the_style_document_names_every_test_here"
    ]
    missing = [name for name in names if name not in document]

    assert missing == []

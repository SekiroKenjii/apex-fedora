"""A module may import from strictly lower layers and from nothing else.

The rule is checked over the real import graph rather than trusted to review, because the
whole design rests on the lowest layer staying pure.
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "src" / "apex"

LAYERS = {
    "kernel": 0,
    "model": 1,
    "ports": 2,
    "registry": 3,
    "pipeline": 4,
    "config": 5,
    "targeting": 5,
    "attestation": 6,
    "workspace": 6,
    "trust": 6,
    "provisioning": 6,
    "composition": 6,
    "verification": 6,
    "adapters": 7,
    "wiring": 8,
    "cli": 9,
    "guest": 10,
}

EFFECT_MODULES = frozenset({
    "subprocess", "socket", "fcntl", "shutil", "tempfile", "time", "uuid", "secrets",
})
EFFECT_FREE_LAYERS = frozenset({"kernel", "model", "ports", "registry", "pipeline"})


def modules() -> Iterator[tuple[Path, ast.Module]]:
    for path in sorted(SOURCE.rglob("*.py")):
        yield path, ast.parse(path.read_text(), filename=str(path))


def package_of(path: Path) -> str:
    relative = path.relative_to(SOURCE)
    return relative.parts[0] if len(relative.parts) > 1 else relative.stem


def imported_names(tree: ast.Module) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def test_the_kernel_imports_nothing_from_the_project_above_itself() -> None:
    offenders = []
    for path, tree in modules():
        if package_of(path) != "kernel":
            continue
        for name in imported_names(tree):
            if name.startswith("apex.") and not name.startswith("apex.kernel"):
                offenders.append(f"{path.name} imports {name}")

    assert offenders == []


def test_the_kernel_imports_only_the_standard_library() -> None:
    offenders = []
    for path, tree in modules():
        if package_of(path) != "kernel":
            continue
        for name in imported_names(tree):
            root = name.split(".")[0]
            if root == "apex" or root in sys.stdlib_module_names:
                continue
            offenders.append(f"{path.name} imports {name}")

    assert offenders == []


def test_no_module_imports_a_higher_layer() -> None:
    offenders = []
    for path, tree in modules():
        package = package_of(path)
        if package not in LAYERS:
            continue
        for name in imported_names(tree):
            if not name.startswith("apex."):
                continue
            target = name.split(".")[1]
            if target not in LAYERS:
                continue
            if LAYERS[target] > LAYERS[package]:
                offenders.append(f"{package} imports {target}")

    assert offenders == []


def test_the_pure_layers_never_reach_for_an_effect_module() -> None:
    offenders = []
    for path, tree in modules():
        if package_of(path) not in EFFECT_FREE_LAYERS:
            continue
        for name in imported_names(tree):
            if name.split(".")[0] in EFFECT_MODULES:
                offenders.append(f"{path.name} imports {name}")

    assert offenders == []


def test_no_module_uses_a_relative_import_beyond_its_package() -> None:
    offenders = []
    for path, tree in modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level > 1:
                offenders.append(f"{path.name} uses a level-{node.level} relative import")

    assert offenders == []


def test_no_assert_statement_survives_in_the_package() -> None:
    """`python -O` deletes assert, and 51 load-bearing checks currently rely on it."""
    offenders = [
        f"{path.relative_to(SOURCE)}:{node.lineno}"
        for path, tree in modules()
        for node in ast.walk(tree)
        if isinstance(node, ast.Assert)
    ]

    assert offenders == []


@pytest.mark.parametrize("package", sorted(LAYERS))
def test_every_declared_layer_that_exists_has_a_docstring(package: str) -> None:
    target = SOURCE / package
    module = target / "__init__.py" if target.is_dir() else SOURCE / f"{package}.py"
    if not module.is_file():
        pytest.skip(f"NOT TESTED: {package} is not built yet")

    assert ast.get_docstring(ast.parse(module.read_text()))


def test_integrity_paths_never_reach_for_a_cached_digest() -> None:
    """Replay re-hashes. A digest read from a cache is a digest an editor can arrange.

    The cache is keyed on the stat tuple, which is right for the immutable object store and
    wrong for anything a verifier decides on. Keeping the port out of this package is what
    stops the two from being confused later.
    """
    offenders = []
    for path, tree in modules():
        if package_of(path) != "attestation":
            continue
        for name in imported_names(tree):
            if name.endswith("digesting"):
                offenders.append(f"{path.name} imports {name}")

    assert offenders == []

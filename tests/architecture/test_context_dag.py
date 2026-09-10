"""The six contexts share a layer, so the layer rule cannot order them.

`attestation` and `workspace` are both layer six and the dependency rule compares with a strict
greater-than, which means workspace importing attestation passes it. The order between contexts
is a real constraint of the design: workspace comes first and nothing it does may depend on how
evidence is judged.
"""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "src" / "apex"

# Earlier contexts may not import later ones. Position in this tuple is the whole rule.
ORDER = ("workspace", "trust", "attestation", "provisioning", "composition", "verification")
POSITION = {name: index for index, name in enumerate(ORDER)}


def context_of(path: Path) -> str | None:
    package = path.relative_to(SOURCE).parts[0]
    return package if package in POSITION else None


def imported_names(tree: ast.Module) -> list[str]:
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.append(node.module)
    return names


def test_no_context_imports_a_later_context() -> None:
    offenders = []
    for path in sorted(SOURCE.rglob("*.py")):
        origin = context_of(path)
        if origin is None:
            continue
        for name in imported_names(ast.parse(path.read_text(), filename=str(path))):
            parts = name.split(".")
            if len(parts) < 2 or parts[0] != "apex":
                continue
            target = parts[1]
            if target in POSITION and POSITION[target] > POSITION[origin]:
                offenders.append(f"{path.name}: {origin} imports {target}")

    assert offenders == []


def test_the_declared_order_covers_every_context_directory() -> None:
    """A context added without a position here would be ordered by nothing."""
    present = {
        path.name
        for path in SOURCE.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }
    contexts = present & set(ORDER)

    assert contexts <= set(POSITION)

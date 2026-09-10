"""Supporting a later store must cost one file, and the rule is checked rather than claimed.

The reader package is walked with pkgutil, so a stray module there is a registration nobody
reviewed. And a mark claim constructed anywhere else is the dispatch chain this design exists
to prevent, wearing a different name.
"""

from __future__ import annotations

import ast
from pathlib import Path

from apex.attestation import markclaims, storereaders

SOURCE = Path(__file__).resolve().parents[2] / "src" / "apex"
READERS = SOURCE / "attestation" / "storereaders"
CLAIM_NAMES = {markclaims.MarkAbsent.__name__, markclaims.MarkEquals.__name__}
DECLARE = "declare"


def units() -> list[Path]:
    return sorted(
        path for path in READERS.glob("*.py") if not path.name.startswith("_")
    )


def parsed(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def declarations(tree: ast.Module) -> int:
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == DECLARE
    )


def test_the_reader_package_holds_at_least_one_unit() -> None:
    assert units()


def test_every_module_in_the_reader_package_declares_exactly_one_reader() -> None:
    offenders = [
        f"{path.name} declares {declarations(parsed(path))}"
        for path in units()
        if declarations(parsed(path)) != 1
    ]

    assert offenders == []


def test_no_module_outside_the_reader_package_constructs_a_mark_claim() -> None:
    """Narrowed deliberately: several modules legitimately name a store version.

    `storemark.FIRST_VERSION`, `Marked.version` and the version field on a spec, a reading and a
    table all do. Constructing a claim is the act this rule forbids.
    """
    offenders = []
    for path in sorted(SOURCE.rglob("*.py")):
        if path.is_relative_to(READERS) or path.name == "markclaims.py":
            continue
        for node in ast.walk(parsed(path)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in CLAIM_NAMES
            ):
                offenders.append(f"{path.name} constructs {node.func.attr}")

    assert offenders == []


def test_every_registered_mark_is_claimed_by_exactly_one_module() -> None:
    sealed = storereaders.sealed()
    declared = sum(len(set(spec.marks)) for spec in set(sealed.values()))

    assert len(sealed) == declared


def test_the_absent_mark_and_the_first_version_resolve_to_one_reader() -> None:
    sealed = storereaders.sealed()

    assert sealed.lookup(markclaims.MarkAbsent().key()) is sealed.lookup(
        markclaims.MarkEquals(1).key()
    )

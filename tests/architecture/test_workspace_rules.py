"""Adding a repository rule costs one file, and the rule packages hold nothing else.

The packages are walked with pkgutil, so a module left behind in one of them is a registration
nobody reviewed. And a rule that refuses more than the guard it replaces must carry its reason
on itself, because a central list of blessed exceptions is the edit this design exists to avoid.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from apex.workspace import contentrules, entryrules, messagerules, ruleorigins

SOURCE = Path(__file__).resolve().parents[2] / "src" / "apex"
PACKAGES = ("entryrules", "contentrules", "messagerules")
DECLARE = "declare"


def units(package: str) -> list[Path]:
    directory = SOURCE / "workspace" / package
    return sorted(p for p in directory.glob("*.py") if not p.name.startswith("_"))


def declarations(path: Path) -> int:
    tree = ast.parse(path.read_text(), filename=str(path))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == DECLARE
    )


@pytest.mark.parametrize("package", PACKAGES)
def test_every_module_in_a_rule_package_declares_exactly_one_rule(package: str) -> None:
    offenders = [
        f"{path.name} declares {declarations(path)}"
        for path in units(package)
        if declarations(path) != 1
    ]

    assert offenders == []


@pytest.mark.parametrize("package", PACKAGES)
def test_the_registry_holds_one_rule_for_every_module(package: str) -> None:
    registry = {
        "entryrules": entryrules,
        "contentrules": contentrules,
        "messagerules": messagerules,
    }

    assert len(registry[package].registered()) == len(units(package))


def test_every_added_rule_states_why_it_refuses_more() -> None:
    added = [
        rule
        for rule in (
            *entryrules.registered(),
            *contentrules.registered(),
            *messagerules.registered(),
        )
        if isinstance(rule.origin, ruleorigins.Introduced)
    ]

    assert added
    for rule in added:
        assert isinstance(rule.origin, ruleorigins.Introduced)
        assert len(rule.origin.why) > 40


def test_no_rule_identifier_is_claimed_twice() -> None:
    identifiers = [
        str(rule.id)
        for rule in (
            *entryrules.registered(),
            *contentrules.registered(),
            *messagerules.registered(),
        )
    ]

    assert sorted(identifiers) == sorted(set(identifiers))

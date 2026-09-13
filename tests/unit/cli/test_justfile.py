"""The justfile is rendered from what the commands declare, with every operand quoted."""

from __future__ import annotations

import pytest

from apex.cli import commands, commandspecs, justfile


def test_a_declared_recipe_renders_its_parameters_quoted_under_the_entry_point() -> None:
    recipe = commandspecs.Recipe(
        "test-installer", ("disk", "iso"),
        ("machine", "start", "--disk", "{{disk}}", "--iso", "{{iso}}"),
    )

    rendered = justfile._command_recipe(recipe)  # noqa: SLF001

    assert rendered == (
        "test-installer disk iso:\n"
        '    {{apex}} machine start --disk "{{disk}}" --iso "{{iso}}"\n'
    )


def test_a_placeholder_that_is_not_a_parameter_is_a_fault() -> None:
    recipe = commandspecs.Recipe("broken", ("disk",), ("machine", "start", "{{iso}}"))

    with pytest.raises(ValueError, match="broken"):
        justfile._command_recipe(recipe)  # noqa: SLF001


def test_every_declared_recipe_names_its_own_command_first() -> None:
    registered = commands.sealed()
    for name in commands.names():
        for recipe in registered.lookup(name).recipes:
            assert recipe.argv[0] == name, recipe.name


def test_recipe_names_are_unique_across_commands_tools_and_the_older_tree() -> None:
    registered = commands.sealed()
    declared = [
        recipe.name for name in commands.names() for recipe in registered.lookup(name).recipes
    ]
    plain = [
        name for name, _, _ in (
            *justfile.FOLDED, *justfile.HOST_PIPELINES, *justfile.TOOLING,
        )
    ]
    names = [*declared, *plain, "gate", "default"]

    assert len(names) == len(set(names))


def test_the_rendering_starts_with_the_header_and_ends_with_the_gate() -> None:
    rendered = justfile.render()

    assert rendered.startswith(justfile.HEADER)
    assert rendered.rstrip("\n").endswith(justfile.GATE[-1])
    assert "    just justfile\n" in rendered
    assert "python3 tools/apex.py test-vm" not in rendered
    assert "python3 tools/apex.py builder" not in rendered

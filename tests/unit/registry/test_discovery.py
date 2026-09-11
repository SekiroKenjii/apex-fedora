"""Discovery is eager and ordered."""

from __future__ import annotations

from apex.registry import discovery


def test_module_names_are_walked_in_sorted_order() -> None:
    walked = discovery.module_names("apex.kernel")

    assert walked == sorted(walked)
    assert "apex.kernel.verdicts" in walked


def test_walking_an_absent_package_is_empty() -> None:
    assert discovery.module_names("apex.no_such_package") == []


def test_discovery_imports_every_module_in_the_namespace() -> None:
    imported = discovery.discover(["apex.kernel"])

    assert "apex.kernel.identifiers" in imported
    assert imported == sorted(imported)


def test_private_modules_are_not_units() -> None:
    assert not [name for name in discovery.module_names("apex.ports") if ".__" in name]

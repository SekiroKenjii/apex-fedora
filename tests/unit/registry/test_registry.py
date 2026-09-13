"""A registry that is open, then sealed, and never both."""

from __future__ import annotations

import dataclasses

import pytest

from apex.kernel import errors
from apex.registry import provenance, registry


@dataclasses.dataclass(frozen=True, slots=True)
class Widget:
    id: str
    summary: str


def where(line: int = 1) -> provenance.Provenance:
    return provenance.Provenance(module="apex.example.widget", qualname="WIDGET", line=line)


def test_a_registration_is_readable_after_sealing() -> None:
    open_registry: registry.Registry[str, Widget] = registry.Registry("widget")
    open_registry.add("a", Widget("a", "first"), at=where())

    sealed = open_registry.seal()

    assert sealed["a"].summary == "first"


def test_a_lookup_before_sealing_is_a_defect() -> None:
    open_registry: registry.Registry[str, Widget] = registry.Registry("widget")
    open_registry.add("a", Widget("a", "first"), at=where())

    with pytest.raises(errors.RegistrationError):
        open_registry.lookup("a")


def test_a_registration_after_sealing_is_refused() -> None:
    open_registry: registry.Registry[str, Widget] = registry.Registry("widget")
    open_registry.seal()

    with pytest.raises(errors.RegistrationError):
        open_registry.add("a", Widget("a", "first"), at=where())


def test_a_duplicate_key_names_both_places_it_came_from() -> None:
    open_registry: registry.Registry[str, Widget] = registry.Registry("widget")
    open_registry.add("a", Widget("a", "first"), at=where(10))

    with pytest.raises(errors.RegistrationError) as raised:
        open_registry.add("a", Widget("a", "second"), at=where(20))

    assert "line 10" in str(raised.value)
    assert "line 20" in str(raised.value)


def test_the_sealed_mapping_cannot_be_written_to() -> None:
    open_registry: registry.Registry[str, Widget] = registry.Registry("widget")
    open_registry.add("a", Widget("a", "first"), at=where())
    sealed = open_registry.seal()

    with pytest.raises(TypeError):
        sealed["b"] = Widget("b", "sneaked in")  # type: ignore[index]


def test_iteration_is_ordered_by_key_regardless_of_registration_order() -> None:
    first: registry.Registry[str, Widget] = registry.Registry("widget")
    for name in ("c", "a", "b"):
        first.add(name, Widget(name, name), at=where())

    second: registry.Registry[str, Widget] = registry.Registry("widget")
    for name in ("b", "c", "a"):
        second.add(name, Widget(name, name), at=where())

    assert list(first.seal()) == list(second.seal()) == ["a", "b", "c"]


def test_sealing_twice_is_a_defect() -> None:
    open_registry: registry.Registry[str, Widget] = registry.Registry("widget")
    open_registry.seal()

    with pytest.raises(errors.RegistrationError):
        open_registry.seal()


def test_provenance_is_kept_for_every_unit() -> None:
    open_registry: registry.Registry[str, Widget] = registry.Registry("widget")
    open_registry.add("a", Widget("a", "first"), at=where(42))

    sealed = open_registry.seal()

    assert sealed.provenance("a").line == 42


def test_an_unknown_key_names_what_is_registered() -> None:
    open_registry: registry.Registry[str, Widget] = registry.Registry("widget")
    open_registry.add("a", Widget("a", "first"), at=where())
    sealed = open_registry.seal()

    with pytest.raises(errors.RegistrationError) as raised:
        sealed.lookup("absent")

    assert "a" in str(raised.value)

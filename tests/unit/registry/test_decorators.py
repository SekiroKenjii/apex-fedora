"""Declaring a unit records where it was declared, without anyone writing it down."""

from __future__ import annotations

import pytest

from apex.kernel import claims, errors, identifiers
from apex.registry import decorators, descriptors


def test_declaring_a_check_records_its_module_and_line() -> None:
    collected: decorators.Collector = decorators.Collector()

    spec = collected.check(
        descriptors.CheckSpec(
            id=identifiers.CheckId("boot.ten-cycles"),
            group="vm",
            environment=claims.EnvironmentKind.VM,
            summary="ten offline boots reach a desktop",
        )
    )

    origin = collected.checks.seal().provenance(str(spec.id))
    assert origin.module == __name__
    assert origin.line > 0


def test_a_declaration_returns_the_specification_unchanged() -> None:
    collected = decorators.Collector()
    spec = descriptors.CheckSpec(
        id=identifiers.CheckId("signature.accept"),
        group="build",
        environment=claims.EnvironmentKind.BUILD,
        summary="a signed bundle verifies",
    )

    assert collected.check(spec) is spec


def test_two_declarations_of_one_identifier_are_refused() -> None:
    collected = decorators.Collector()
    spec = descriptors.CheckSpec(
        id=identifiers.CheckId("boot.ten-cycles"),
        group="vm",
        environment=claims.EnvironmentKind.VM,
        summary="first",
    )
    collected.check(spec)

    with pytest.raises(errors.RegistrationError):
        collected.check(spec)


def test_a_hardware_check_must_require_a_physical_environment() -> None:
    with pytest.raises(errors.RegistrationError):
        descriptors.CheckSpec(
            id=identifiers.CheckId("audio.speakers"),
            group="hardware",
            environment=claims.EnvironmentKind.VM,
            summary="the speakers make a sound",
        )


def test_a_hardware_check_declaring_physical_is_accepted() -> None:
    spec = descriptors.CheckSpec(
        id=identifiers.CheckId("audio.speakers"),
        group="hardware",
        environment=claims.EnvironmentKind.PHYSICAL,
        summary="the speakers make a sound",
    )

    assert spec.environment is claims.EnvironmentKind.PHYSICAL


def test_a_check_declaring_a_simulated_environment_is_refused() -> None:
    with pytest.raises(errors.RegistrationError):
        descriptors.CheckSpec(
            id=identifiers.CheckId("boot.ten-cycles"),
            group="vm",
            environment=claims.EnvironmentKind.SIMULATED,
            summary="nothing a fake can prove",
        )


def test_a_check_without_a_summary_is_refused() -> None:
    with pytest.raises(errors.RegistrationError):
        descriptors.CheckSpec(
            id=identifiers.CheckId("boot.ten-cycles"),
            group="vm",
            environment=claims.EnvironmentKind.VM,
            summary="",
        )

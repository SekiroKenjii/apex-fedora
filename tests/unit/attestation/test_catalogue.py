"""The catalogue is the registry, not a JSON list.

A check that is not registered does not exist, so the fold cannot report ready by forgetting
one. Registering a new check makes it blocking the instant it lands.
"""

from __future__ import annotations

import json
from pathlib import Path

from apex.attestation import catalogue
from apex.kernel import claims

REPOSITORY = Path(__file__).resolve().parents[3]
GROUP_SIZES = {"build": 11, "vm": 27, "hardware": 16, "recovery": 5, "git": 3}


def test_every_check_in_the_stored_catalogue_is_registered() -> None:
    stored = json.loads((REPOSITORY / "config" / "checks.json").read_text())
    expected = {name for names in stored.values() for name in names}

    assert {str(item) for item in catalogue.sealed()} == expected


def test_the_group_sizes_match_the_stored_catalogue() -> None:
    counted = dict.fromkeys(GROUP_SIZES, 0)
    for spec in catalogue.sealed().values():
        counted[spec.group] += 1

    assert counted == GROUP_SIZES


def test_the_catalogue_holds_sixty_two_checks() -> None:
    assert len(catalogue.sealed()) == 62


def test_every_hardware_check_requires_a_physical_environment() -> None:
    for spec in catalogue.sealed().values():
        if spec.group == "hardware":
            assert spec.environment is claims.EnvironmentKind.PHYSICAL


def test_no_check_can_be_satisfied_by_simulation() -> None:
    for spec in catalogue.sealed().values():
        assert spec.environment is not claims.EnvironmentKind.SIMULATED


def test_every_check_states_what_it_establishes() -> None:
    for spec in catalogue.sealed().values():
        assert len(spec.summary) > 30, f"{spec.id} says too little"


def test_every_check_names_the_proof_kinds_it_accepts() -> None:
    for spec in catalogue.sealed().values():
        assert spec.accepted_proof_kinds
        for kind in spec.accepted_proof_kinds:
            assert kind.startswith(".")


def test_no_check_accepts_an_arbitrary_binary_proof() -> None:
    """The suffix allowlist is the only barrier against storing biometric material."""
    permitted = {".txt", ".log", ".json", ".png", ".ppm", ".xml"}
    for spec in catalogue.sealed().values():
        assert set(spec.accepted_proof_kinds) <= permitted


def test_each_check_is_declared_in_its_own_module() -> None:
    sealed = catalogue.sealed()
    modules = {sealed.provenance(key).module for key in sealed}

    assert len(modules) == len(sealed)


def test_a_check_module_records_where_its_summary_came_from() -> None:
    for spec in catalogue.sealed().values():
        assert spec.sourced_from, f"{spec.id} does not say where its summary came from"

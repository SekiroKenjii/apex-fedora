"""The operator's command surface may grow. It may not shift under them."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from migration import surface_contract

REPOSITORY = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(shutil.which("just") is None, reason="NOT TESTED: just is absent")


def frozen() -> dict[str, surface_contract.Recipe]:
    document = json.loads(surface_contract.CONTRACT.read_text())
    return {
        str(item["name"]): surface_contract.Recipe(
            str(item["name"]),
            tuple(
                surface_contract.Parameter(str(p["name"]), bool(p["required"]))
                for p in item["parameters"]
            ),
        )
        for item in document["recipes"]
    }


def test_the_contract_is_committed_and_names_its_baseline() -> None:
    document = json.loads(surface_contract.CONTRACT.read_text())

    assert document["revision"] == surface_contract.BASELINE_REVISION
    assert len(document["recipes"]) >= 50


def test_the_live_justfile_still_covers_every_frozen_recipe() -> None:
    live = surface_contract.dump(REPOSITORY / "Justfile")

    assert surface_contract.violations(frozen(), live) == []


def test_a_removed_recipe_is_a_violation() -> None:
    contract = frozen()
    live = dict(contract)
    live.pop("doctor")

    assert surface_contract.violations(contract, live) == ["doctor: recipe was removed or renamed"]


def test_a_changed_operand_list_is_a_violation() -> None:
    contract = frozen()
    live = dict(contract)
    live["artifact"] = surface_contract.Recipe(
        "artifact", (surface_contract.Parameter("kind", True),)
    )

    problems = surface_contract.violations(contract, live)

    assert len(problems) == 1
    assert problems[0].startswith("artifact: operands changed")


def test_adding_a_recipe_is_allowed() -> None:
    contract = frozen()
    live = dict(contract)
    live["brand-new"] = surface_contract.Recipe("brand-new", ())

    assert surface_contract.violations(contract, live) == []


def test_an_optional_parameter_is_not_a_required_operand() -> None:
    contract = frozen()

    assert contract["build"].required_names == ()
    assert contract["artifact"].required_names == ("kind", "build_id")

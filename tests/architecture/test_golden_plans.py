"""Every recipe's derived plan is frozen under version control and matches what is derived."""

from __future__ import annotations

import json

from migration import golden_plans


def test_every_recipe_has_a_frozen_plan_that_matches() -> None:
    assert golden_plans.differences() == []


def test_the_frozen_plan_records_the_derived_order_and_digest() -> None:
    document = json.loads((golden_plans.DIRECTORY / "export-source.json").read_text())

    assert [stage["id"] for stage in document["stages"]] == [
        "run.identify",
        "source.locate",
        "source.bundle",
        "source.manifest",
    ]
    assert len(document["digest"]) == 64

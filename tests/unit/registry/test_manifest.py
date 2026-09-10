"""A registry without a manifest trades an editable list for invisible behaviour."""

from __future__ import annotations

import json

from apex.kernel import claims, identifiers
from apex.registry import decorators, descriptors, manifest


def collected() -> decorators.Collector:
    collector = decorators.Collector()
    collector.check(
        descriptors.CheckSpec(
            id=identifiers.CheckId("signature.accept"),
            group="build",
            environment=claims.EnvironmentKind.BUILD,
            summary="a signed bundle verifies against the trusted key",
        )
    )
    collector.check(
        descriptors.CheckSpec(
            id=identifiers.CheckId("audio.speakers"),
            group="hardware",
            environment=claims.EnvironmentKind.PHYSICAL,
            summary="the built-in speakers produce audible sound",
        )
    )
    return collector


def test_the_manifest_lists_every_registered_unit() -> None:
    document = manifest.render(collected())

    names = [item["id"] for item in document["checks"]]
    assert names == ["audio.speakers", "signature.accept"]


def test_the_manifest_records_where_each_unit_was_declared() -> None:
    document = manifest.render(collected())

    for item in document["checks"]:
        assert item["module"]
        assert item["line"] > 0


def test_the_manifest_is_stable_across_renders() -> None:
    assert manifest.render(collected()) == manifest.render(collected())


def test_the_manifest_serialises_to_sorted_json() -> None:
    text = manifest.serialise(manifest.render(collected()))

    assert json.loads(text)["checks"][0]["id"] == "audio.speakers"
    assert text.endswith("\n")


def test_a_new_unit_appears_as_one_added_entry() -> None:
    before = manifest.render(collected())

    collector = collected()
    collector.check(
        descriptors.CheckSpec(
            id=identifiers.CheckId("boot.grub-counter"),
            group="vm",
            environment=claims.EnvironmentKind.VM,
            summary="the boot counter falls back after two failures",
        )
    )
    after = manifest.render(collector)

    added = [item for item in after["checks"] if item not in before["checks"]]
    assert [item["id"] for item in added] == ["boot.grub-counter"]

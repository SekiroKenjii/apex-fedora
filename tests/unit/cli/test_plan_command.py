"""The plan command prints what the frozen plans hold and touches nothing."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from apex.cli import commandspecs
from apex.cli.commands import plan_command
from apex.composition.recipes import disk_artifact_recipe, image_recipe
from apex.config import loader
from apex.kernel import errors, identifiers, safepaths
from apex.model import release
from apex.pipeline import plans
from apex.ports import portset
from apex.targeting import releases
from apex.targeting.releases import fedora44_release
from apex.verification.recipes import desktop_theme_recipe
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]


def request(ports: portset.HostPorts, *arguments: str) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=loader.load(host_file=None, environment={}),
            repository=safepaths.SourceRoot.adopt(REPOSITORY),
            root=None,
            environment={},
            bundle=lambda _root: ports,
        ),
    )


def test_an_artifact_kind_names_its_recipe_and_the_document_is_the_frozen_one(
    ports: portset.HostPorts,
) -> None:
    for kind, recipe in (("image", image_recipe), ("qcow2", disk_artifact_recipe),
                         ("installer", disk_artifact_recipe)):
        reply = plan_command.run(request(ports, "artifact", kind))

        assert reply.document == plans.render(recipe.PLAN), kind
        frozen = REPOSITORY / "generated" / "plans" / f"{recipe.NAME}.json"
        assert reply.document == json.loads(frozen.read_text())
        assert reply.exit_code == 0 and reply.narrative == ""


def test_a_verification_recipe_is_planned_by_the_check_it_records(
    ports: portset.HostPorts,
) -> None:
    reply = plan_command.run(request(ports, "verify", "desktop-theme"))

    assert reply.document == plans.render(desktop_theme_recipe.PLAN)
    assert not ports.guest.runs  # type: ignore[attr-defined]


def test_an_upgrade_to_a_release_no_module_declares_prints_the_template_and_exits_three(
    ports: portset.HostPorts,
) -> None:
    reply = plan_command.run(request(ports, "upgrade", "--release", "fedora-45"))

    assert reply.exit_code == errors.PreconditionUnmet.exit_code
    assert reply.document is None and reply.text is not None
    assert 'identifiers.ProfileId("fedora-45")' in reply.text
    assert "fedora45_release.py" in reply.narrative


def test_an_upgrade_to_a_declared_release_prints_the_four_lists_and_writes_nothing(
    ports: portset.HostPorts, monkeypatch: pytest.MonkeyPatch
) -> None:
    later = dataclasses.replace(
        fedora44_release.PROFILE, id=identifiers.ProfileId("fedora-45"), major=45,
        dist_tag=release.DistTag("fc45"),
    )
    monkeypatch.setattr(
        releases, "lookup", lambda name: later if str(name) == "fedora-45" else None
    )

    reply = plan_command.run(request(ports, "upgrade", "--release", "fedora-45"))

    assert reply.exit_code == 0 and isinstance(reply.document, dict)
    assert reply.document["target"] == "fedora-45"
    assert reply.document["writes"] == []
    assert any("fc44" in item for item in reply.document["pins_to_review"])  # type: ignore[union-attr]
    assert reply.document["attestations_to_redo"] == []

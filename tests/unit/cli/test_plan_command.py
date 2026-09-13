"""The plan command prints what the frozen plans hold and touches nothing."""

from __future__ import annotations

import json
from pathlib import Path

from apex.cli import commandspecs
from apex.cli.commands import plan_command
from apex.composition.recipes import disk_artifact_recipe, image_recipe
from apex.config import loader
from apex.kernel import safepaths
from apex.pipeline import plans
from apex.ports import portset
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

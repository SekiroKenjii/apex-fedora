"""Print the derived order of a recipe with its effects, and touch nothing.

Planning has no effect by construction: the stages are ordered from what they read and
write, and the document here is the same one the frozen copy under `generated/plans/` holds,
so an operator reads what the gate checks.
"""

from __future__ import annotations

import argparse

from apex.cli import commands, commandspecs
from apex.composition.recipes import disk_artifact_recipe, image_recipe, live_artifact_recipe
from apex.model import builds
from apex.pipeline import plans
from apex.ports import portset
from apex.verification.recipes import desktop_theme_recipe, live_protection_recipe

NAME = "plan"
SUMMARY = "the derived order of a recipe, with what each stage reads, writes and affects"
ARTIFACT = "artifact"
VERIFY = "verify"
ARTIFACTS: dict[str, plans.Plan[portset.HostPorts]] = {
    str(builds.ArtifactKind.IMAGE): image_recipe.PLAN,
    str(builds.ArtifactKind.QCOW2): disk_artifact_recipe.PLAN,
    str(builds.ArtifactKind.INSTALLER): disk_artifact_recipe.PLAN,
    str(builds.ArtifactKind.LIVE): live_artifact_recipe.PLAN,
}
VERIFICATIONS: dict[str, plans.Plan[portset.HostPorts]] = {
    "live-protection": live_protection_recipe.PLAN,
    "desktop-theme": desktop_theme_recipe.PLAN,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    subjects = parser.add_subparsers(dest="subject", required=True)
    artifact = subjects.add_parser(ARTIFACT, help="a build recipe by the artifact it makes")
    artifact.add_argument("kind", choices=sorted(ARTIFACTS))
    verify = subjects.add_parser(VERIFY, help="a verification recipe by the check it records")
    verify.add_argument("recipe", choices=sorted(VERIFICATIONS))
    return parser


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    if arguments.subject == ARTIFACT:
        plan = ARTIFACTS[arguments.kind]
    else:
        plan = VERIFICATIONS[arguments.recipe]
    return commandspecs.Reply(document=plans.render(plan))


commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run))

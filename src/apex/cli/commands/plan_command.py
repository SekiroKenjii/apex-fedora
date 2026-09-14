"""Print what a recipe or a release upgrade would do, and touch nothing.

Planning has no effect by construction: the stages are ordered from what they read and
write, and the document here is the same one the frozen copy under `generated/plans/` holds,
so an operator reads what the gate checks. An upgrade plan reads the two profiles, the
reviewed locks and the store, and prints four lists; a profile that does not exist yet is
printed as the module to write, with the exit code of an unmet precondition.
"""

from __future__ import annotations

import argparse

from apex.attestation import reading
from apex.cli import commands, commandspecs
from apex.composition.recipes import disk_artifact_recipe, image_recipe, live_artifact_recipe
from apex.config import locksurvey
from apex.kernel import errors, identifiers
from apex.model import builds
from apex.pipeline import plans
from apex.ports import portset
from apex.targeting import releases, upgrading
from apex.verification.recipes import desktop_theme_recipe, live_protection_recipe

NAME = "plan"
SUMMARY = "what a recipe or a release upgrade would do, read from what is declared"
ARTIFACT = "artifact"
VERIFY = "verify"
UPGRADE = "upgrade"
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
    upgrade = subjects.add_parser(UPGRADE, help="what moving to another release would touch")
    upgrade.add_argument("--release", required=True, help="the profile id to move to")
    return parser


def _upgrade(request: commandspecs.Request, target_name: str) -> commandspecs.Reply:
    target_id = identifiers.ProfileId(target_name)
    current = releases.current()
    target = releases.lookup(target_id)
    if target is None:
        module = upgrading.module_name(target_id)
        return commandspecs.Reply(
            text=upgrading.template(target_id, current),
            narrative=(
                f"no profile declares {target_id}; write targeting/releases/{module} from the "
                "template on standard output, then plan again\n"
            ),
            exit_code=errors.PreconditionUnmet.exit_code,
        )
    attestations: list[str] = []
    root = request.context.root
    if root is not None:
        found = reading.read_store(root.path, files=request.context.bundle(root).files)
        attestations = [item.check for item in found.attestations]
    planned = upgrading.plan(
        current,
        target,
        locks=locksurvey.reviewed_locks(request.context.repository),
        attestations=attestations,
    )
    return commandspecs.Reply(document=planned.document())


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    if arguments.subject == UPGRADE:
        return _upgrade(request, arguments.release)
    if arguments.subject == ARTIFACT:
        plan = ARTIFACTS[arguments.kind]
    else:
        plan = VERIFICATIONS[arguments.recipe]
    return commandspecs.Reply(document=plans.render(plan))


RECIPES = (
    commandspecs.Recipe("plan-artifact", ("kind",), (NAME, ARTIFACT, "{{kind}}")),
    commandspecs.Recipe("plan-verify", ("recipe",), (NAME, VERIFY, "{{recipe}}")),
    commandspecs.Recipe("plan-upgrade", ("release",), (NAME, UPGRADE, "--release", "{{release}}")),
)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

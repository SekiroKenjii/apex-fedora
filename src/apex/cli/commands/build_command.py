"""Build the image, or derive a disk or the live medium from one, in the running builder.

The recipes are the composition's; this command reads what the operator chose and the
lease of the running builder, and seeds them. A derived artifact names the completed
image build it comes from; a QCOW2 may carry a disposable account for the tests that
log in, and nothing else may. The reply is the run's record, and a build the guest
failed is reported with the log it retained.
"""

from __future__ import annotations

import argparse
import dataclasses

from apex.cli import commands, commandspecs
from apex.composition import exports, keys
from apex.composition.recipes import disk_artifact_recipe, image_recipe, live_artifact_recipe
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.model import builds, machines
from apex.pipeline import runner
from apex.ports import guestshell, portset
from apex.provisioning import launching
from apex.wiring import contexts

NAME = "build"
SUMMARY = "build the image, or derive a disk or the live medium, in the running builder"
IMAGE = "image"
TEST_ACCESS = "test-access"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    parser.add_argument("kind", choices=[str(kind) for kind in builds.ArtifactKind])
    parser.add_argument(
        "--profile", choices=[str(profile) for profile in builds.Profile],
        default=str(builds.Profile.FEDORA), help="the image's profile; an image build only",
    )
    parser.add_argument("--parent", help="the completed image build a derived artifact comes from")
    parser.add_argument(
        f"--{TEST_ACCESS}", action="store_true",
        help="a disposable account with a key and a password; a qcow2 only",
    )
    return parser


@dataclasses.dataclass(frozen=True, slots=True)
class Request:
    kind: builds.ArtifactKind
    profile: builds.Profile
    parent: identifiers.BuildId | None
    test_access: bool

    @classmethod
    def parse(cls, arguments: argparse.Namespace) -> Request:
        kind = builds.ArtifactKind(str(arguments.kind))
        parent = None if arguments.parent is None else identifiers.BuildId.parse(arguments.parent)
        if kind.derived and parent is None:
            raise errors.Refusal(
                refusals.RefusalReason.BUILD_PARENT_REQUIRED,
                subject=f"a {kind} artifact is derived from a completed image build",
                remedy="name that build with --parent",
            )
        if not kind.derived and parent is not None:
            raise errors.Refusal(
                refusals.RefusalReason.REQUEST_MALFORMED,
                subject="an image build has no parent",
                remedy="drop --parent, or name the artifact to derive",
            )
        return cls(
            kind=kind, profile=builds.Profile(str(arguments.profile)), parent=parent,
            test_access=bool(arguments.test_access),
        )


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: no runtime root to build from",
        )
    return context.root


def _builder(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    lease = launching.current(ports, root=root)
    if lease is None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_NOT_RUNNING,
            subject="no machine is running",
            remedy="start the builder first",
        )
    if lease.intent.role is not machines.VmRole.BUILDER:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_ROLE_MISMATCH,
            subject=f"a {lease.intent.role} machine is running",
            remedy="a build runs in the isolated builder",
        )
    key = root.child(defaults.BUILDER_KEY_NAME)
    if not key.path.is_file():
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject=f"{key}: prepare the builder first",
        )
    return guestshell.GuestTarget(
        user=defaults.BUILDER_USER,
        port=defaults.BUILDER_SSH_PORT,
        key=safepaths.SafePath.regular_file(key.path, within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def _run(
    ports: portset.HostPorts,
    request: Request,
    *,
    repository: safepaths.SourceRoot,
    root: safepaths.RuntimeRoot,
    builder: guestshell.GuestTarget,
) -> runner.Outcome:
    if request.kind is builds.ArtifactKind.IMAGE:
        return image_recipe.build(
            ports, repository=repository, runtime_root=root, builder=builder,
            profile=request.profile,
        )
    parent = request.parent
    if parent is None:
        raise errors.InternalDefect("a derived request without a parent passed parsing")
    if request.kind is builds.ArtifactKind.LIVE:
        return live_artifact_recipe.derive(
            ports, repository=repository, runtime_root=root, builder=builder, parent=parent
        )
    return disk_artifact_recipe.derive(
        ports, repository=repository, runtime_root=root, builder=builder,
        kind=request.kind, parent=parent, test_access=request.test_access,
    )


def _document(outcome: runner.Outcome, root: safepaths.RuntimeRoot) -> encoding.Document:
    run = outcome.facts.get(keys.RUN_ID)
    record = outcome.facts.get(keys.BUILD_RECORD)
    access = outcome.facts.get(keys.ACCESS)
    return {
        "succeeded": outcome.succeeded,
        "run": None if run is None else str(run),
        "exports": None if run is None else str(exports.inside(root, run, "")),
        "record": None if record is None else record.document(),
        "access": None if access is None else access.document(),
        "refusal": None if outcome.refusal is None else str(outcome.refusal),
        "detail": outcome.detail,
    }


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    asked = Request.parse(arguments)
    root = _root(request.context)
    ports = request.context.bundle(root)
    builder = _builder(ports, root)
    outcome = _run(
        ports, asked, repository=request.context.repository, root=root, builder=builder
    )
    document = _document(outcome, root)
    if outcome.succeeded:
        return commandspecs.Reply(document=document)
    exit_code = errors.Refusal.exit_code if outcome.refusal is not None else 1
    return commandspecs.Reply(
        document=document, narrative=f"{NAME}: {outcome.detail}\n", exit_code=exit_code
    )


RECIPES = (
    commandspecs.Recipe("build", ('profile="fedora"',), (NAME, IMAGE, "--profile", "{{profile}}")),
    commandspecs.Recipe(
        "artifact", ("kind", "build_id"), (NAME, "{{kind}}", "--parent", "{{build_id}}")
    ),
    commandspecs.Recipe(
        "test-disk", ("build_id",),
        (NAME, str(builds.ArtifactKind.QCOW2), "--parent", "{{build_id}}", f"--{TEST_ACCESS}"),
    ),
)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

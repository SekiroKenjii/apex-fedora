"""Build the image, or derive an artifact from one, in the running builder.

The recipes are the composition's and the verification's; this command reads what the
operator chose and the lease of the running builder, and seeds them. A derived artifact
names the completed image build it comes from; a QCOW2 may carry a disposable account for
the tests that log in, and nothing else may. The fingerprint packages are built from the
sources alone, the fingerprint image from a parent, a package build and a dialog test; the
installer fixture disks and the update fixtures are made by the agent in the builder; the
recovery disk comes from image A of a completed update fixture. The reply is the run's
record, and a build the guest failed is reported with the log it retained.
"""

from __future__ import annotations

import argparse
import dataclasses
from collections.abc import Callable

from apex.cli import builderaccess, commands, commandspecs, verifyinputs
from apex.composition import exports, keys
from apex.composition.recipes import (
    disk_artifact_recipe,
    fingerprint_image_recipe,
    fingerprint_rpms_recipe,
    image_recipe,
    live_artifact_recipe,
    nvidia_recipe,
)
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.model import builds
from apex.pipeline import runner
from apex.ports import guestshell, portset
from apex.verification import updatefixtures, verifykeys
from apex.verification.recipes import (
    installer_fixtures_recipe,
    recovery_disk_recipe,
    update_fixtures_recipe,
)
from apex.wiring import contexts

NAME = "build"
SUMMARY = "build the image, or derive a disk, a medium, packages or a fixture, in the builder"
IMAGE = "image"
FIXTURES = "fixtures"
UPDATE_FIXTURES = "update-fixtures"
RECOVERY_DISK = "recovery-disk"
TEST_ACCESS = "test-access"
PARENT, RPM_BUILD, GTK_TEST, FIXTURE = "parent", "rpm-build", "gtk-test", "fixture"
KINDS = (*(str(kind) for kind in builds.ArtifactKind), FIXTURES, UPDATE_FIXTURES, RECOVERY_DISK)
DERIVED = frozenset({PARENT})
DISKS = frozenset({PARENT, TEST_ACCESS})
OPERANDS: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    IMAGE: (frozenset(), frozenset()),
    str(builds.ArtifactKind.QCOW2): (DERIVED, DISKS),
    str(builds.ArtifactKind.INSTALLER): (DERIVED, DISKS),
    str(builds.ArtifactKind.LIVE): (DERIVED, DERIVED),
    str(builds.ArtifactKind.NVIDIA): (DERIVED, DERIVED),
    str(builds.ArtifactKind.FINGERPRINT_RPMS): (frozenset(), frozenset()),
    str(builds.ArtifactKind.FINGERPRINT_IMAGE): (
        frozenset({PARENT, RPM_BUILD, GTK_TEST}), frozenset({PARENT, RPM_BUILD, GTK_TEST}),
    ),
    FIXTURES: (frozenset(), frozenset()),
    UPDATE_FIXTURES: (DERIVED, DERIVED),
    RECOVERY_DISK: (frozenset({FIXTURE}), frozenset({FIXTURE})),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument(
        "--profile", choices=[str(profile) for profile in builds.Profile],
        default=str(builds.Profile.FEDORA), help="the image's profile; an image build only",
    )
    parser.add_argument(
        f"--{PARENT}", help="the completed image build a derived artifact comes from"
    )
    parser.add_argument(
        f"--{TEST_ACCESS}", action="store_true",
        help="a disposable account with a key and a password; a qcow2 only",
    )
    parser.add_argument(f"--{RPM_BUILD}", help="the completed fingerprint package build")
    parser.add_argument(f"--{GTK_TEST}", help="the passed fingerprint dialog test run")
    parser.add_argument(f"--{FIXTURE}", help="a completed update fixture, by run or directory")
    return parser


@dataclasses.dataclass(frozen=True, slots=True)
class Request:
    """What to build, with every operand the kind takes and none it does not."""

    kind: str
    profile: builds.Profile
    parent: identifiers.BuildId | None
    test_access: bool
    rpm_build: identifiers.BuildId | None
    gtk_test: identifiers.BuildId | None
    fixture: str | None

    @classmethod
    def parse(cls, arguments: argparse.Namespace) -> Request:
        kind = str(arguments.kind)
        given = {
            name for name, value in (
                (PARENT, arguments.parent), (TEST_ACCESS, arguments.test_access),
                (RPM_BUILD, arguments.rpm_build), (GTK_TEST, arguments.gtk_test),
                (FIXTURE, arguments.fixture),
            ) if value
        }
        required, permitted = OPERANDS[kind]
        if PARENT in required - given:
            raise errors.Refusal(
                refusals.RefusalReason.BUILD_PARENT_REQUIRED,
                subject=f"a {kind} artifact is derived from a completed image build",
                remedy=f"name that build with --{PARENT}",
            )
        if required - given or given - permitted:
            raise errors.Refusal(
                refusals.RefusalReason.REQUEST_MALFORMED,
                subject=f"{kind} takes {_spelt(permitted)} and needs {_spelt(required)}",
                remedy=f"given: {_spelt(frozenset(given))}",
            )
        return cls(
            kind=kind, profile=builds.Profile(str(arguments.profile)),
            parent=_build_id(arguments.parent), test_access=bool(arguments.test_access),
            rpm_build=_build_id(arguments.rpm_build), gtk_test=_build_id(arguments.gtk_test),
            fixture=arguments.fixture,
        )


def _spelt(names: frozenset[str]) -> str:
    return ", ".join(f"--{name}" for name in sorted(names)) or "no option"


def _build_id(value: str | None) -> identifiers.BuildId | None:
    return None if value is None else identifiers.BuildId.parse(value)


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: no runtime root to build from",
        )
    return context.root


@dataclasses.dataclass(frozen=True, slots=True)
class Seeds:
    ports: portset.HostPorts
    request: Request
    repository: safepaths.SourceRoot
    root: safepaths.RuntimeRoot
    builder: guestshell.GuestTarget

    def parent(self) -> identifiers.BuildId:
        if self.request.parent is None:
            raise errors.InternalDefect("a derived request without a parent passed parsing")
        return self.request.parent

    def wheel(self) -> safepaths.SafePath:
        return verifyinputs.wheel(self.root)


def _image(seeds: Seeds) -> runner.Outcome:
    return image_recipe.build(
        seeds.ports, repository=seeds.repository, runtime_root=seeds.root,
        builder=seeds.builder, profile=seeds.request.profile,
    )


def _disk(seeds: Seeds) -> runner.Outcome:
    return disk_artifact_recipe.derive(
        seeds.ports, repository=seeds.repository, runtime_root=seeds.root,
        builder=seeds.builder, kind=builds.ArtifactKind(seeds.request.kind),
        parent=seeds.parent(), test_access=seeds.request.test_access,
    )


def _live(seeds: Seeds) -> runner.Outcome:
    return live_artifact_recipe.derive(
        seeds.ports, repository=seeds.repository, runtime_root=seeds.root,
        builder=seeds.builder, parent=seeds.parent(),
    )


def _nvidia(seeds: Seeds) -> runner.Outcome:
    return nvidia_recipe.build(
        seeds.ports, repository=seeds.repository, runtime_root=seeds.root,
        builder=seeds.builder, parent=seeds.parent(),
    )


def _fingerprint_rpms(seeds: Seeds) -> runner.Outcome:
    return fingerprint_rpms_recipe.build(
        seeds.ports, repository=seeds.repository, runtime_root=seeds.root, builder=seeds.builder
    )


def _fingerprint_image(seeds: Seeds) -> runner.Outcome:
    rpm_build, gtk_test = seeds.request.rpm_build, seeds.request.gtk_test
    if rpm_build is None or gtk_test is None:
        raise errors.InternalDefect("a fingerprint image request without its tests passed parsing")
    return fingerprint_image_recipe.build(
        seeds.ports, repository=seeds.repository, runtime_root=seeds.root,
        builder=seeds.builder, parent=seeds.parent(), rpm_build=rpm_build, gtk_test=gtk_test,
    )


def _fixtures(seeds: Seeds) -> runner.Outcome:
    return installer_fixtures_recipe.build(
        seeds.ports, builder=seeds.builder, wheel=seeds.wheel(), root=seeds.root
    )


def _update_fixtures(seeds: Seeds) -> runner.Outcome:
    return update_fixtures_recipe.build(
        seeds.ports, builder=seeds.builder, wheel=seeds.wheel(), parent=seeds.parent(),
        root=seeds.root, repository=seeds.repository,
    )


def _recovery_disk(seeds: Seeds) -> runner.Outcome:
    located = updatefixtures.locate(seeds.ports, seeds.root, str(seeds.request.fixture))
    return recovery_disk_recipe.build(
        seeds.ports, repository=seeds.repository, runtime_root=seeds.root,
        builder=seeds.builder, wheel=seeds.wheel(), fixture=located,
    )


RECIPES_BY_KIND: dict[str, Callable[[Seeds], runner.Outcome]] = {
    IMAGE: _image,
    str(builds.ArtifactKind.QCOW2): _disk,
    str(builds.ArtifactKind.INSTALLER): _disk,
    str(builds.ArtifactKind.LIVE): _live,
    str(builds.ArtifactKind.NVIDIA): _nvidia,
    str(builds.ArtifactKind.FINGERPRINT_RPMS): _fingerprint_rpms,
    str(builds.ArtifactKind.FINGERPRINT_IMAGE): _fingerprint_image,
    FIXTURES: _fixtures,
    UPDATE_FIXTURES: _update_fixtures,
    RECOVERY_DISK: _recovery_disk,
}


def _document(outcome: runner.Outcome, root: safepaths.RuntimeRoot) -> encoding.Document:
    run = outcome.facts.get(keys.RUN_ID)
    record = outcome.facts.get(keys.BUILD_RECORD)
    access = outcome.facts.get(keys.ACCESS)
    fixtures = outcome.facts.get(verifykeys.FIXTURES)
    return {
        "succeeded": outcome.succeeded,
        "run": None if run is None else str(run),
        "exports": None if run is None else str(exports.inside(root, run, "")),
        "record": None if record is None else record.document(),
        "access": None if access is None else access.document(),
        "fixtures": None if fixtures is None else str(fixtures),
        "nvidia": outcome.facts.get(keys.NVIDIA_REPORT),
        "fingerprint": outcome.facts.get(keys.FINGERPRINT_REPORT),
        "refusal": None if outcome.refusal is None else str(outcome.refusal),
        "detail": outcome.detail,
    }


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    asked = Request.parse(arguments)
    root = _root(request.context)
    ports = request.context.bundle(root)
    seeds = Seeds(
        ports=ports, request=asked, repository=request.context.repository, root=root,
        builder=builderaccess.leased_builder(ports, root),
    )
    outcome = RECIPES_BY_KIND[asked.kind](seeds)
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
        "artifact", ("kind", "build_id"), (NAME, "{{kind}}", f"--{PARENT}", "{{build_id}}")
    ),
    commandspecs.Recipe(
        "test-disk", ("build_id",),
        (NAME, str(builds.ArtifactKind.QCOW2), f"--{PARENT}", "{{build_id}}", f"--{TEST_ACCESS}"),
    ),
    commandspecs.Recipe("installer-fixtures", (), (NAME, FIXTURES)),
    commandspecs.Recipe(
        "build-nvidia", ("build_id",),
        (NAME, str(builds.ArtifactKind.NVIDIA), f"--{PARENT}", "{{build_id}}"),
    ),
    commandspecs.Recipe(
        "build-fingerprint-rpms", (), (NAME, str(builds.ArtifactKind.FINGERPRINT_RPMS))
    ),
    commandspecs.Recipe(
        "build-fingerprint-image", ("parent_build", "rpm_build", "gtk_test"),
        (
            NAME, str(builds.ArtifactKind.FINGERPRINT_IMAGE), f"--{PARENT}", "{{parent_build}}",
            f"--{RPM_BUILD}", "{{rpm_build}}", f"--{GTK_TEST}", "{{gtk_test}}",
        ),
    ),
    commandspecs.Recipe(
        "update-fixtures", ("build_id",), (NAME, UPDATE_FIXTURES, f"--{PARENT}", "{{build_id}}")
    ),
    commandspecs.Recipe(
        "recovery-disk", ("fixture",), (NAME, RECOVERY_DISK, f"--{FIXTURE}", "{{fixture}}")
    ),
)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

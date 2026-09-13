"""Select a completed, verified image build as the candidate under test.

The build's record must say a passing image build; its output is verified against a key the
operator supplies from outside it before its digest is written as the candidate, and the
previous candidate's document is kept under its own run. Selection is for testing; the
readiness fold decides installation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from apex.attestation import selecting
from apex.cli import commands, commandspecs
from apex.cli.commands import trust_command
from apex.composition import exports
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.model import builds
from apex.ports import portset
from apex.trust import anchors, verifying
from apex.wiring import contexts

NAME = "candidate"
SUMMARY = "select a verified image build as the candidate under test"
SELECT = "select"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    actions = parser.add_subparsers(dest="action", required=True)
    chosen = actions.add_parser(SELECT, help="verify a completed image build and select it")
    chosen.add_argument("--build", required=True, help="the completed image build")
    chosen.add_argument("--key", required=True, type=Path, help="the trusted public key")
    return parser


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: no runtime root to select in",
        )
    return context.root


def _completed_image(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, build: identifiers.BuildId
) -> builds.BuildRecord:
    path = exports.inside(root, build, builds.RECORD_NAME)
    if not ports.files.exists(path):
        raise errors.Refusal(
            refusals.RefusalReason.BUILD_PARENT_NOT_COMPLETE,
            subject=f"build {build} left no {builds.RECORD_NAME}",
        )
    record = builds.BuildRecord.parse(
        ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)
    )
    if record.status is not builds.BuildStatus.PASS or record.kind is not builds.ArtifactKind.IMAGE:
        raise errors.Refusal(
            refusals.RefusalReason.BUILD_PARENT_NOT_COMPLETE,
            subject=f"build {build} is {record.status} {record.kind}",
            remedy="select a completed image build",
        )
    return record


def select(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, build: str, key: Path
) -> encoding.Document:
    parsed = identifiers.BuildId.parse(build)
    _completed_image(ports, root, parsed)
    verified = verifying.verify_bundle(
        ports, location=trust_command.location(root, build),
        anchor=anchors.operator_supplied(key),
    )
    selected = selecting.select(
        ports, root=root, digest=verified.digest, build=parsed,
        verification=trust_command.verified_document(ports, verified),
        run=ports.identities.run_id(),
    )
    return selected.document()


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    root = _root(request.context)
    ports = request.context.bundle(root)
    return commandspecs.Reply(document=select(ports, root, arguments.build, arguments.key))


RECIPES = (
    commandspecs.Recipe(
        "select-candidate", ("build_id", "key"),
        (NAME, SELECT, "--build", "{{build_id}}", "--key", "{{key}}"),
    ),
)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

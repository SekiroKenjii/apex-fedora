"""Verify a signed bundle, exercise the verifier against it, and keep the builder's key.

A bundle is judged only against a key the operator supplies from outside it, and only where
a build left it, under the runtime root's exports. The exercise runs every registered
negative over a scratch copy and files its results beside them, as the older tool did, so
a passing verification is worth citing. The development key comes over the builder's own
channel and never from a bundle.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from apex.cli import builderaccess, commands, commandspecs
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.model import builds
from apex.ports import portset
from apex.trust import anchors, developmentkey, exercising, negatives, verifying
from apex.wiring import contexts

NAME = "trust"
SUMMARY = "verify a signed bundle, exercise the verifier, or keep the builder's development key"
VERIFY, EXERCISE, DEVELOPMENT_KEY = "verify", "exercise", "development-key"
NOT_TESTED = "NOT TESTED"
PASS = "PASS"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    actions = parser.add_subparsers(dest="action", required=True)
    for action, text in (
        (VERIFY, "verify the signed output of a build against a key supplied from outside it"),
        (EXERCISE, "run every registered negative against a verified bundle and file the results"),
    ):
        judged = actions.add_parser(action, help=text)
        judged.add_argument("--build", required=True, help="the build whose output is judged")
        judged.add_argument("--key", required=True, type=Path, help="the trusted public key")
    actions.add_parser(DEVELOPMENT_KEY, help="fetch the builder's development public key")
    return parser


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: no runtime root to judge in",
        )
    return context.root


def location(root: safepaths.RuntimeRoot, build: str) -> verifying.BundleLocation:
    parsed = identifiers.BuildId.parse(build)
    return verifying.BundleLocation(
        root=root, relative=f"{defaults.EXPORT_DIRECTORY}/{parsed}/{builds.OUTPUT_DIRECTORY}"
    )


def verified_document(
    ports: portset.HostPorts, verified: verifying.VerifiedBundle
) -> encoding.Document:
    """The older tool's verification result, field for field."""
    return {
        "status": PASS,
        "digest": str(verified.digest),
        "purpose": verified.manifest.purpose,
        "trusted_key_sha256": ports.digests.file(
            safepaths.SafePath(verified.anchor.public_key.path)
        ).hex,
        "files_verified": verified.files_verified,
        "bootc_update_policy": NOT_TESTED,
    }


def verify(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, build: str, key: Path
) -> encoding.Document:
    verified = verifying.verify_bundle(
        ports, location=location(root, build), anchor=anchors.operator_supplied(key)
    )
    return verified_document(ports, verified)


def exercise(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, build: str, key: Path
) -> encoding.Document:
    run = ports.identities.run_id()
    scratch = verifying.BundleLocation(
        root=root, relative=f"{defaults.SIGNATURE_TESTS_DIRECTORY}/{run}"
    )
    ports.files.make_directory(scratch.directory(), mode=safepaths.PRIVATE_DIRECTORY_MODE)
    trial = negatives.Trial(location=location(root, build), anchor=anchors.operator_supplied(key))
    report = exercising.exercise(ports, trial=trial, scratch=scratch)
    results: encoding.Document = {
        "digest": str(report.accepted.digest),
        "status": PASS,
        "checks": dict.fromkeys(report.refused, PASS),
        "refused": {name: str(reason) for name, reason in report.refused.items()},
        "accepted_bundle": verified_document(ports, report.accepted),
        "bootc_updates": NOT_TESTED,
    }
    proof = scratch.entry(defaults.RESULTS_NAME)
    ports.files.write_atomic(proof, encoding.canonical(results) + b"\n", mode=defaults.RECORD_MODE)
    return {**results, "proof": str(proof)}


def development_key(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> encoding.Document:
    builder = builderaccess.leased_builder(ports, root)
    return developmentkey.retrieve(ports, builder=builder, root=root).document()


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    root = _root(request.context)
    ports = request.context.bundle(root)
    if arguments.action == VERIFY:
        return commandspecs.Reply(document=verify(ports, root, arguments.build, arguments.key))
    if arguments.action == EXERCISE:
        return commandspecs.Reply(document=exercise(ports, root, arguments.build, arguments.key))
    return commandspecs.Reply(document=development_key(ports, root))


RECIPES = (
    commandspecs.Recipe(
        "trust-verify", ("build_id", "key"),
        (NAME, VERIFY, "--build", "{{build_id}}", "--key", "{{key}}"),
    ),
    commandspecs.Recipe(
        "trust-exercise", ("build_id", "key"),
        (NAME, EXERCISE, "--build", "{{build_id}}", "--key", "{{key}}"),
    ),
    commandspecs.Recipe("trust-development-key", (), (NAME, DEVELOPMENT_KEY)),
)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

"""Prove on the host what needs no machine, and record each check through the real ports.

`git` asks disposable repositories what the three git checks state, through the hooks as
Git calls them. `signature` verifies a build's signed output against a key from outside it,
runs every registered negative over a copy, and refuses a build whose output is not the
selected candidate, since a record citing another build blocks readiness. Each record is
minted as a run's would be: the judged report is the proof, the host bundle the witness,
and the imported record it replaces is superseded in the chain.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from apex.cli import commands, commandspecs, hookkinds, hookspecs
from apex.cli.commands import trust_command
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths, verdicts
from apex.model import runtimestate
from apex.ports import portset
from apex.trust import anchors, verifying
from apex.verification import hostproofs
from apex.wiring import contexts
from apex.workspace import hookproving, rulespecs

NAME = "prove"
SUMMARY = "prove a check on the host with no machine, and record it through the real ports"
GIT = "git"
SIGNATURE = "signature"
ACCEPT = identifiers.CheckId("signature.accept")
REJECT = identifiers.CheckId("signature.reject")
FAILED_EXIT = 1
PROVERS = (hookproving.commit_policy, hookproving.private_stage, hookproving.outgoing_history)
NEGATIVE_FAULTS = frozenset(
    {refusals.RefusalReason.NEGATIVE_ACCEPTED, refusals.RefusalReason.NEGATIVE_WRONG_REASON}
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    families = parser.add_subparsers(dest="family", required=True)
    families.add_parser(GIT, help="the three git checks, over disposable repositories")
    signed = families.add_parser(SIGNATURE, help="the two signature checks, over a build")
    signed.add_argument("--build", required=True, help="the candidate's build")
    signed.add_argument("--key", required=True, type=Path, help="the trusted public key")
    return parser


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: no runtime root to record into",
        )
    return context.root


def _candidate(root: safepaths.RuntimeRoot) -> identifiers.Digest:
    document = root.child(runtimestate.CANDIDATE_NAME)
    if not document.path.is_file():
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject=f"{document}: select a candidate before proving",
        )
    return runtimestate.read_candidate(document.path).digest


def _inspect(ports: portset.HostPorts) -> hookproving.Inspect:
    def inspect(
        hook: str, repository: Path, arguments: Sequence[str], standard_input: str
    ) -> Sequence[rulespecs.Finding]:
        kind = hookkinds.lookup(hook)
        if kind is None:
            raise errors.InternalDefect(f"{hook}: no hook kind answers to it")
        return kind.inspect(
            hookspecs.HookRequest(
                repository=repository,
                arguments=tuple(arguments),
                standard_input=standard_input,
                processes=ports.processes,
            )
        )

    return inspect


def git(minter: hostproofs.Minter, root: safepaths.RuntimeRoot) -> list[encoding.Document]:
    ports = minter.ports
    scratch = root.child(f"{defaults.GIT_PROOFS_DIRECTORY}/{ports.identities.run_id()}")
    ports.files.make_directory(scratch, mode=safepaths.PRIVATE_DIRECTORY_MODE)
    bench = hookproving.Bench(
        processes=ports.processes, filesystem=ports.files, scratch=scratch, inspect=_inspect(ports)
    )
    return [
        minter.mint(proven.check, proven.verdict, proven.observations)
        for proven in (prover(bench) for prover in PROVERS)
    ]


def _exercised(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, build: str, key: Path
) -> tuple[verdicts.Verdict, encoding.Document]:
    """The exercise's results, or the negative the verifier got wrong as a failed result."""
    try:
        return verdicts.PASSED, trust_command.exercise(ports, root, build, key)
    except errors.Refusal as refusal:
        if refusal.reason not in NEGATIVE_FAULTS:
            raise
        return verdicts.FAILED, {"reason": refusal.reason.value, "subject": refusal.subject}


def signature(
    minter: hostproofs.Minter, root: safepaths.RuntimeRoot, build: str, key: Path
) -> list[encoding.Document]:
    ports = minter.ports
    verified = verifying.verify_bundle(
        ports, location=trust_command.location(root, build), anchor=anchors.operator_supplied(key)
    )
    if str(verified.digest) != str(minter.candidate):
        raise errors.Refusal(
            refusals.RefusalReason.RECORD_NOT_BOUND_TO_CANDIDATE,
            subject=f"build {build} signed {verified.digest}; the candidate is {minter.candidate}",
            remedy="select that build as the candidate, or prove the candidate's own build",
        )
    accepted = minter.mint(
        ACCEPT, verdicts.PASSED, trust_command.verified_document(ports, verified)
    )
    verdict, results = _exercised(ports, root, build, key)
    return [accepted, minter.mint(REJECT, verdict, results)]


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    root = _root(request.context)
    ports = request.context.bundle(root)
    minter = hostproofs.Minter(ports, root, _candidate(root))
    if arguments.family == GIT:
        recorded = git(minter, root)
    else:
        recorded = signature(minter, root, str(arguments.build), Path(arguments.key))
    passed = all(item["verdict"] == verdicts.PASSED.stored_name for item in recorded)
    return commandspecs.Reply(
        document={"recorded": recorded}, exit_code=0 if passed else FAILED_EXIT
    )


RECIPES = (
    commandspecs.Recipe("prove-git", (), (NAME, GIT)),
    commandspecs.Recipe(
        "prove-signature",
        ("build_id", "key"),
        (NAME, SIGNATURE, "--build", "{{build_id}}", "--key", "{{key}}"),
    ),
)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

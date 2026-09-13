"""Record one result for a check by hand, with the operator's proofs and the operator's note.

This is the older `record`: a check the catalogue names, a status, the environment it was
witnessed in, a description and a reason, and the files that prove it. The minting rules
refuse what they always refused, a hardware result from a machine, a pass without proof, a
kind the check does not accept, before any byte lands. The operator's description and
reason are filed as the record's first proof, a small document, because the chain's entry
has no field for prose and the words are evidence of what was done.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from apex.attestation import minting
from apex.cli import commands, commandspecs
from apex.config import defaults
from apex.kernel import claims, encoding, errors, identifiers, refusals, safepaths, verdicts
from apex.model import runtimestate
from apex.ports import portset
from apex.verification import recording
from apex.wiring import contexts

NAME = "record"
SUMMARY = "record one result for a check with the operator's proofs and note"
STATUSES = tuple(sorted({
    verdicts.Passed.stored_name, verdicts.Failed.stored_name, verdicts.Blocked.stored_name,
}))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    parser.add_argument("check")
    parser.add_argument("status", choices=STATUSES)
    parser.add_argument(
        "--environment", required=True,
        choices=[str(kind) for kind in claims.ATTESTABLE],
    )
    parser.add_argument("--description", required=True)
    parser.add_argument("--proof", type=Path, action="append", default=[])
    parser.add_argument("--reason", default="")
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
            subject=f"{document}: select a candidate before recording",
        )
    return runtimestate.read_candidate(document.path).digest


def note(description: str, reason: str, environment: claims.EnvironmentKind) -> minting.Offered:
    document: encoding.Document = {
        "description": description, "reason": reason, "environment": str(environment),
    }
    return minting.Offered(payload=encoding.canonical(document), kind=defaults.OPERATOR_NOTE_KIND)


def offered(ports: portset.HostPorts, proofs: list[Path]) -> list[minting.Offered]:
    found = []
    for path in proofs:
        regular = safepaths.RegularFile.adopt(path)
        payload = ports.files.read_bytes(
            safepaths.SafePath(regular.path), limit=defaults.PROOF_LIMIT.value
        )
        found.append(minting.Offered(payload=payload, kind=regular.path.suffix.lower()))
    return found


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    root = _root(request.context)
    ports = request.context.bundle(root)
    environment = claims.EnvironmentKind(str(arguments.environment))
    if arguments.status == verdicts.Passed.stored_name and not arguments.proof:
        raise errors.Refusal(
            refusals.RefusalReason.PASS_REQUIRES_PROOF,
            subject=str(arguments.check),
            remedy="a passing result cites at least one proof file beyond the note",
        )
    recorder = recording.Recorder.open(
        root, filesystem=ports.files, identities=ports.identities, clock=ports.clock
    )
    recorded = recorder.record(
        check=identifiers.CheckId(str(arguments.check)),
        verdict=verdicts.parse(
            str(arguments.status), reason=refusals.RefusalReason.MALFORMED_VERDICT
        ),
        offered=[
            note(str(arguments.description), str(arguments.reason), environment),
            *offered(ports, list(arguments.proof)),
        ],
        candidate=_candidate(root),
        witnessed=claims.witnessed_through(ports.environment, environment),
    )
    return commandspecs.Reply(document={
        "recorded": {
            "check": str(recorded.check),
            "verdict": recorded.verdict.stored_name,
            "sequence": recorded.sequence,
            "proofs": [digest.hex for digest in recorded.proofs],
        }
    })


commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run))

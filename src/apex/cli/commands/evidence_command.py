"""Replay the attestation chain and name the first entry that does not hold.

An empty chain is a true answer rather than a skipped check. The key sits beside the chain,
laid down when the store was first opened for writing; before that, an environment variable
may name one. A broken link means an edit made without the key or a file damaged by
something else, never proof that the operator changed the chain deliberately.
"""

from __future__ import annotations

import argparse

from apex.attestation import ledger, proofs
from apex.cli import commands, commandspecs
from apex.kernel import encoding, safepaths, secrets
from apex.ports import portset

NAME = "evidence"
SUMMARY = "the attestation chain, replayed"
VERIFY_CHAIN = "verify-chain"
KEY_VARIABLE = "APEX_CHAIN_KEY"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    parser.add_argument("action", choices=[VERIFY_CHAIN])
    return parser


def inspect(
    root: safepaths.RuntimeRoot, ports: portset.HostPorts, *, fallback_key: str
) -> encoding.Document:
    location = proofs.StoreLocation(root=root)
    lines, head = ledger.read_chain(location, ports.files)
    signer = ledger.signer_at(location, ports.files) or ledger.ChainSigner(
        secrets.Secret(fallback_key)
    )
    report = ledger.replay(lines, signer=signer, head=head)
    first_break: encoding.JsonValue = None
    if report.first_break is not None:
        first_break = {
            "sequence": report.first_break.sequence,
            "cause": str(report.first_break.cause),
        }
    return {"entries": report.entries, "intact": report.intact, "first_break": first_break}


def run(request: commandspecs.Request) -> commandspecs.Reply:
    _parser().parse_args(list(request.arguments))
    root = request.context.root
    if root is None:
        return commandspecs.Reply(document={"skipped": "no runtime root on this machine"})
    result = inspect(
        root, request.context.bundle(root),
        fallback_key=request.context.environment.get(KEY_VARIABLE, ""),
    )
    if result["intact"]:
        return commandspecs.Reply(document=result)
    return commandspecs.Reply(
        document=result, narrative="The attestation chain is broken\n", exit_code=1
    )


RECIPES = (commandspecs.Recipe("verify-chain", (), (NAME, VERIFY_CHAIN)),)

commands.declare(
    commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES)
)

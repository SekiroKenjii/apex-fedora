"""Read the store through the versioned reader and say what it holds.

The verdict map is the fold's; the table is the same reading laid out for an operator, with
what strict readiness withholds shown beside it. An intake fault, a damaged, linked or
unbound record, makes the exit code non-zero, which is what keeps the reader's error
handling gated rather than merely tested. Read only: nothing under the runtime root is
created.
"""

from __future__ import annotations

import argparse

from apex.attestation import columns, readiness, reading, resolving, retracting
from apex.cli import commands, commandspecs, rendering
from apex.kernel import safepaths
from apex.ports import portset

NAME = "readiness"
SUMMARY = "the verdict of every check in the catalogue over the store"
CANDIDATE_DOCUMENT = "candidate.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    parser.add_argument("--strict", action="store_true", help="withhold imported passes")
    parser.add_argument("--table", action="store_true", help="a table instead of a document")
    return parser


def tabulate(
    root: safepaths.RuntimeRoot, ports: portset.HostPorts, *, strict: bool
) -> columns.Table:
    found = reading.read_store(root.path, files=ports.files)
    outcome = readiness.evaluate(
        required=resolving.required_environments(), records=found.records, candidate=found.candidate
    )
    withheld: tuple[retracting.Withheld, ...] = ()
    if strict:
        outcome, withheld = retracting.retract(outcome, attestations=found.attestations)
    return columns.tabulate(reading=found, outcome=outcome, withheld=withheld, strict=strict)


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    root = request.context.root
    if root is None:
        return commandspecs.Reply(document={"skipped": "no runtime root on this machine"})
    ports = request.context.bundle(root)
    if not ports.files.exists(root.child(CANDIDATE_DOCUMENT)):
        return commandspecs.Reply(document={"skipped": "no candidate in this runtime root"})
    table = tabulate(root, ports, strict=arguments.strict)
    narrative = f"{len(table.faults)} intake faults\n" if table.faults else ""
    exit_code = 1 if table.faults else 0
    if arguments.table:
        return commandspecs.Reply(
            text=rendering.render(table), narrative=narrative, exit_code=exit_code
        )
    return commandspecs.Reply(
        document=columns.document(table), narrative=narrative, exit_code=exit_code
    )


RECIPES = (
    commandspecs.Recipe("readiness", (), (NAME,)),
    commandspecs.Recipe("report", (), (NAME,)),
    commandspecs.Recipe("readiness-table", (), (NAME, "--table")),
    commandspecs.Recipe("readiness-table-strict", (), (NAME, "--table", "--strict")),
)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

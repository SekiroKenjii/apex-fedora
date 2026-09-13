"""The physical host's own tools: a read-only snapshot, a bus trace, a coefficient decoded.

The fingerprint trace reads a monitor transcript from standard input, which the justfile
pipes from a bounded, privileged bus monitor; the collector itself runs as the operator and
refuses root. An incomplete capture is reported with its own exit code, never as observed.
"""

from __future__ import annotations

import argparse
import os

from apex.cli import commands, commandspecs
from apex.kernel import errors, refusals, safepaths
from apex.verification import fingerprinttrace, hardwaresnapshot, hdacoefficient
from apex.wiring import contexts

NAME = "hardware"
SUMMARY = "observe the host's audio and fingerprint state, or decode a codec coefficient"
SNAPSHOT = "snapshot"
DECODE = "decode-coefficient"
OBSERVE = "observe-fingerprint"
LOOKUP = "lookup-system-clients"
INCOMPLETE_EXIT_CODE = 2
ROOT_USER = 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser(SNAPSHOT, help="read-only audio and fingerprint observations, kept once")
    decode = actions.add_parser(DECODE, help="a coefficient command as integers, no device")
    decode.add_argument("nid")
    decode.add_argument("verb")
    decode.add_argument("parameter")
    observe = actions.add_parser(
        OBSERVE, help="reduce a busctl monitor transcript on stdin to fprintd ownership events"
    )
    observe.add_argument(
        f"--{LOOKUP}", action="store_true", help="name the process behind each client"
    )
    return parser


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: no runtime root to keep observations in",
        )
    return context.root


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    if arguments.action == DECODE:
        return commandspecs.Reply(document=hdacoefficient.decode(
            hdacoefficient.operand(arguments.nid, "nid"),
            hdacoefficient.operand(arguments.verb, "verb"),
            hdacoefficient.operand(arguments.parameter, "parameter"),
        ))
    root = _root(request.context)
    if arguments.action == OBSERVE:
        return _observe(request, root, lookup=bool(arguments.lookup_system_clients))
    written = hardwaresnapshot.collect(request.context.bundle(root), root)
    return commandspecs.Reply(
        document={"observations": str(written), "scope": hardwaresnapshot.SCOPE}
    )


def _observe(
    request: commandspecs.Request, root: safepaths.RuntimeRoot, *, lookup: bool
) -> commandspecs.Reply:
    if os.geteuid() == ROOT_USER:
        raise errors.Refusal(
            refusals.RefusalReason.HOST_RUNS_AS_ROOT,
            subject="the collector keeps files as the operator",
            remedy="run it as your normal user, after the privileged monitor pipe",
        )
    captured = fingerprinttrace.capture(
        request.context.bundle(root), root, request.read_input().encode(),
        lookup_clients=lookup,
    )
    document = {**captured.summary, "directory": str(captured.directory)}
    if captured.observed:
        return commandspecs.Reply(document=document)
    return commandspecs.Reply(
        document=document,
        narrative=f"{OBSERVE}: the capture is incomplete; see {captured.directory}\n",
        exit_code=INCOMPLETE_EXIT_CODE,
    )


RECIPES = (commandspecs.Recipe("hardware-snapshot", (), (NAME, SNAPSHOT)),)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

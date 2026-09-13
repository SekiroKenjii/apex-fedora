"""The physical host's own tools: a read-only snapshot, and a coefficient decoded on paper."""

from __future__ import annotations

import argparse

from apex.cli import commands, commandspecs
from apex.kernel import errors, refusals, safepaths
from apex.verification import hardwaresnapshot, hdacoefficient
from apex.wiring import contexts

NAME = "hardware"
SUMMARY = "observe the host's audio and fingerprint state, or decode a codec coefficient"
SNAPSHOT = "snapshot"
DECODE = "decode-coefficient"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser(SNAPSHOT, help="read-only audio and fingerprint observations, kept once")
    decode = actions.add_parser(DECODE, help="a coefficient command as integers, no device")
    decode.add_argument("nid")
    decode.add_argument("verb")
    decode.add_argument("parameter")
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
    written = hardwaresnapshot.collect(request.context.bundle(root), root)
    return commandspecs.Reply(
        document={"observations": str(written), "scope": hardwaresnapshot.SCOPE}
    )


RECIPES = (commandspecs.Recipe("hardware-snapshot", (), (NAME, SNAPSHOT)),)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

"""Compile the reviewed fingerprint patches' handlers against test shims on the host."""

from __future__ import annotations

import argparse
from pathlib import Path

from apex.cli import commands, commandspecs
from apex.kernel import errors, refusals, safepaths
from apex.verification import dialogcheck, elancheck
from apex.wiring import contexts

NAME = "patch"
SUMMARY = "compile a reviewed fingerprint patch's handlers against test shims on the host"
DIALOG = "fingerprint-dialog"
ELAN = "elan-diagnostics"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    actions = parser.add_subparsers(dest="action", required=True)
    for action, text in (
        (DIALOG, "GNOME's dialog handlers, unpatched and patched, over twelve scenarios"),
        (ELAN, "libfprint's ELAN diagnostic helpers over twenty synthetic transfers"),
    ):
        checked = actions.add_parser(action, help=text)
        checked.add_argument(
            "--source", type=Path, required=True, help="the reviewed C source the lock names"
        )
    return parser


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: no runtime root to keep results in",
        )
    return context.root


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    root = _root(request.context)
    ports = request.context.bundle(root)
    if arguments.action == DIALOG:
        checked = dialogcheck.check(ports, root, request.context.repository, arguments.source)
    else:
        checked = elancheck.check(ports, root, request.context.repository, arguments.source)
    cases = checked.document["cases"]
    counted = len(cases) if isinstance(cases, dict) else 0
    return commandspecs.Reply(document={
        "status": checked.document["status"], "cases": counted, "report": str(checked.proof),
    })


RECIPES = (
    commandspecs.Recipe(
        "test-fingerprint-dialog", ("source",), (NAME, DIALOG, "--source", "{{source}}")
    ),
    commandspecs.Recipe(
        "test-elan-diagnostics", ("source",), (NAME, ELAN, "--source", "{{source}}")
    ),
)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

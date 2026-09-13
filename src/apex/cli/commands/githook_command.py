"""One git hook answered by the rules, as the installed three-line hook calls it.

Git passes the message file to the commit message hook as an argument and the update lines
to the pre-push hook on standard input; the command reads that input only for the kind
that needs it, and replies with the rules' text and their exit code.
"""

from __future__ import annotations

import argparse

from apex.cli import commands, commandspecs, hookdispatch, hookkinds
from apex.kernel import errors

NAME = "git-hook"
SUMMARY = "answer one git hook with the repository rules"
READS_INPUT = "pre-push"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    parser.add_argument("kind", choices=hookkinds.names())
    parser.add_argument("arguments", nargs="*")
    return parser


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    processes, _ = request.context.repository_ports()
    standard_input = request.read_input() if arguments.kind == READS_INPUT else ""
    try:
        code, text = hookdispatch.run(
            [str(arguments.kind), *arguments.arguments], standard_input,
            processes=processes, repository=request.context.repository.path,
        )
    except errors.ApexError as failure:
        return commandspecs.Reply(narrative=f"{failure}\n", exit_code=failure.exit_code)
    return commandspecs.Reply(narrative=text, exit_code=code)


commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run))

"""One argument vector in, one exit code out.

A name the registry holds runs as a command with the context the root built; a retired name
is refused with its replacement spelt out; any other name is refused with the names that
exist, since no older tree answers for anything any more. A refusal raised by a command is
rendered with its own exit code, and a parser that stops the run, for help or a wrong
operand, keeps the code it chose.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TextIO

from apex.cli import commands, commandspecs, rendering, retirednames
from apex.kernel import errors, refusals
from apex.wiring import contexts


def _refused(argv: Sequence[str]) -> errors.Refusal:
    name = argv[0] if argv else "(none)"
    replacement = retirednames.replacement(name)
    if replacement is not None:
        return errors.Refusal(
            refusals.RefusalReason.COMMAND_RETIRED,
            subject=f"{name} moved",
            remedy=f"use {replacement}",
        )
    return errors.Refusal(
        refusals.RefusalReason.COMMAND_UNKNOWN,
        subject=name,
        remedy=f"the commands are {', '.join(commands.names())}",
    )


def run(
    argv: Sequence[str],
    *,
    context_of: Callable[[], contexts.Context],
    stdout: TextIO,
    stderr: TextIO,
    stdin: TextIO | None = None,
) -> int:
    command = commands.lookup(argv[0]) if argv else None
    if command is None:
        refusal = _refused(argv)
        rendering.emit(
            commandspecs.Reply(narrative=f"{refusal}\n", exit_code=refusal.exit_code),
            stdout=stdout,
            stderr=stderr,
        )
        return refusal.exit_code
    try:
        reply = command.run(
            commandspecs.Request(
                arguments=tuple(argv[1:]),
                context=context_of(),
                read_input=commandspecs.no_input if stdin is None else stdin.read,
            )
        )
    except errors.ApexError as failure:
        reply = commandspecs.Reply(narrative=f"{failure}\n", exit_code=failure.exit_code)
    except SystemExit as stop:
        return int(stop.code or 0) if not isinstance(stop.code, str) else errors.Refusal.exit_code
    rendering.emit(reply, stdout=stdout, stderr=stderr)
    return reply.exit_code

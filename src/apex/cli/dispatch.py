"""One argument vector in, one exit code out.

A name the registry holds runs as a command with the context the root built; a retired name
is refused with its replacement spelt out; every other name goes to the bridge, so the older
tree keeps answering for what has not moved. A refusal raised by a command is rendered with
its own exit code, and a parser that stops the run, for help or a wrong operand, keeps the
code it chose.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TextIO

from apex.cli import commands, commandspecs, legacy_bridge, rendering
from apex.kernel import errors, refusals
from apex.wiring import contexts


def run(
    argv: Sequence[str],
    *,
    context_of: Callable[[], contexts.Context],
    stdout: TextIO,
    stderr: TextIO,
) -> int:
    command = commands.lookup(argv[0]) if argv else None
    replacement = legacy_bridge.replacement(argv[0]) if argv else None
    if command is None and replacement is not None:
        retired = errors.Refusal(
            refusals.RefusalReason.COMMAND_RETIRED,
            subject=f"{argv[0]} moved",
            remedy=f"use {replacement}",
        )
        rendering.emit(
            commandspecs.Reply(narrative=f"{retired}\n", exit_code=retired.exit_code),
            stdout=stdout, stderr=stderr,
        )
        return retired.exit_code
    if command is None:
        return legacy_bridge.dispatch(list(argv))
    try:
        reply = command.run(commandspecs.Request(arguments=tuple(argv[1:]), context=context_of()))
    except errors.ApexError as failure:
        reply = commandspecs.Reply(narrative=f"{failure}\n", exit_code=failure.exit_code)
    except SystemExit as stop:
        return int(stop.code or 0) if not isinstance(stop.code, str) else errors.Refusal.exit_code
    rendering.emit(reply, stdout=stdout, stderr=stderr)
    return reply.exit_code

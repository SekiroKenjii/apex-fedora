"""Answering one git hook, and never raising at the caller.

The floor check is the reason this module exists rather than being three lines somewhere else.
A registry that loaded no rules refuses nothing and reports nothing, and a guard that permits
everything in silence looks exactly like a guard that is working. The hook reads the
repository through a process port; the installed hook gets the real one from the
composition root, and a test hands in a scripted one.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from apex.cli import hookkinds, hookspecs, refusaltext
from apex.config import defaults
from apex.kernel import errors, refusals
from apex.ports import process
from apex.wiring import hostbundle
from apex.workspace import contentrules, entryrules, messagerules

REPOSITORY = Path(__file__).resolve().parents[3]
PERMITTED = 0


def _loaded() -> None:
    counted = (
        len(entryrules.registered()),
        len(contentrules.registered()),
        len(messagerules.registered()),
    )
    if counted < defaults.REPOSITORY_RULE_FLOOR:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.HOOK_RULES_NOT_LOADED,
            subject=f"loaded {counted}, expected at least {defaults.REPOSITORY_RULE_FLOOR}",
        )


def run(
    argv: Sequence[str],
    standard_input: str,
    footer: str = "",
    *,
    processes: process.ProcessPort,
    repository: Path = REPOSITORY,
) -> tuple[int, str]:
    """The exit code and the text for standard error, empty when the hook permits."""
    _loaded()
    kind = hookkinds.lookup(argv[0]) if argv else None
    if kind is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.HOOK_KIND_UNKNOWN,
            subject=f"{argv[0] if argv else '(none)'} is not a hook the rules answer",
        )
    request = hookspecs.HookRequest(
        repository=repository,
        arguments=tuple(argv[1:]),
        standard_input=standard_input,
        processes=processes,
    )
    findings = kind.inspect(request)
    if not findings:
        return PERMITTED, ""
    text = refusaltext.report(findings, subject=kind.subject, footer=footer or kind.footer)
    return errors.Refusal.exit_code, text


def main(
    argv: Sequence[str],
    standard_input: str = "",
    footer: str = "",
    *,
    processes: process.ProcessPort | None = None,
) -> int:
    """Every refusal keeps the exit code its own kind carries."""
    try:
        code, text = run(
            argv, standard_input, footer,
            processes=hostbundle.processes() if processes is None else processes,
        )
    except errors.ApexError as failure:
        sys.stderr.write(f"{refusaltext.PREFIX}{failure}\n")
        return failure.exit_code
    sys.stderr.write(text)
    return code

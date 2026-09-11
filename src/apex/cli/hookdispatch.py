"""Answering one git hook, and never raising at the caller.

The floor check is the reason this module exists rather than being three lines somewhere else.
A registry that loaded no rules refuses nothing and reports nothing, and a guard that permits
everything in silence looks exactly like a guard that is working.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from apex.cli import hookkinds, hookspecs, refusaltext
from apex.config import defaults
from apex.kernel import errors, refusals
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


def run(argv: Sequence[str], standard_input: str, footer: str) -> int:
    _loaded()
    kind = hookkinds.lookup(argv[0]) if argv else None
    if kind is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.HOOK_KIND_UNKNOWN,
            subject=f"{argv[0] if argv else '(none)'} is not a hook the rules answer",
        )
    request = hookspecs.HookRequest(
        repository=REPOSITORY, arguments=tuple(argv[1:]), standard_input=standard_input
    )
    findings = kind.inspect(request)
    if not findings:
        return PERMITTED
    sys.stderr.write(
        refusaltext.report(findings, subject=kind.subject, footer=footer)
    )
    return errors.Refusal.exit_code


def main(argv: Sequence[str], standard_input: str = "", footer: str = "") -> int:
    """Every refusal keeps the exit code its own kind carries."""
    try:
        return run(argv, standard_input, footer)
    except errors.ApexError as failure:
        sys.stderr.write(f"{refusaltext.PREFIX}{failure}\n")
        return failure.exit_code

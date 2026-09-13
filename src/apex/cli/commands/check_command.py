"""Run every check the architecture is held by, and stop the gate when one fails.

The checks are the ones declared under `workspace/checks/`, in their declared order: the
formatter, ruff, mypy, pyright, vulture, pylint's duplicate rule, the import linter, the
architecture tests, the repository's rules over every tracked file, and the size table.
None runs in a warning mode. The reply names each check's verdict and the tail of what a
failing one printed; the exit code is non-zero when any check failed.
"""

from __future__ import annotations

import argparse

from apex.cli import commands, commandspecs
from apex.config import toolchain
from apex.kernel import encoding
from apex.workspace import checks

NAME = "check"
SUMMARY = "run every check the architecture is held by; any failure fails the command"
ONLY = "only"
LIST = "list"
FAILED_EXIT = 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    parser.add_argument(
        f"--{ONLY}", action="append", default=[], help="run this check alone; repeatable"
    )
    parser.add_argument(
        f"--{LIST}", action="store_true", help="name the checks in order and run none"
    )
    return parser


def _selected(names: list[str]) -> tuple[checks.Check, ...]:
    if not names:
        return checks.registered()
    return tuple(checks.lookup(name) for name in names)


def _document(outcomes: dict[str, checks.Outcome]) -> encoding.Document:
    return {
        "status": checks.PASS if all(o.passed for o in outcomes.values()) else checks.FAIL,
        "checks": [{"id": name, **found.document()} for name, found in outcomes.items()],
    }


def _narrative(outcomes: dict[str, checks.Outcome]) -> str:
    lines = [f"{name}: {found.status}" for name, found in outcomes.items()]
    for name, found in outcomes.items():
        if not found.passed:
            lines.append(f"\n{name} said:\n{found.detail}")
    return "\n".join(lines) + "\n"


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    selected = _selected(list(arguments.only))
    if arguments.list:
        listed: encoding.Document = {
            "checks": [{"id": c.id, "summary": c.summary, "order": c.order} for c in selected]
        }
        return commandspecs.Reply(document=listed)
    processes, filesystem = request.context.repository_ports()
    site = checks.Site(
        processes=processes,
        filesystem=filesystem,
        repository=request.context.repository.path,
        python=toolchain.running_python(),
    )
    outcomes = {check.id: check.run(site) for check in selected}
    passed = all(found.passed for found in outcomes.values())
    return commandspecs.Reply(
        document=_document(outcomes),
        narrative=_narrative(outcomes),
        exit_code=0 if passed else FAILED_EXIT,
    )


RECIPES = (commandspecs.Recipe("check", (), (NAME,)),)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

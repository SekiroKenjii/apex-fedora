"""Say what the host has and what a machine needs, and refuse on any shortfall.

The report is the reply whether or not the host is ready, so the operator reads all of it;
the narrative names every problem, and the exit code is a refusal's when there is one.
"""

from __future__ import annotations

import argparse

from apex.cli import commands, commandspecs
from apex.kernel import errors, refusals, safepaths
from apex.provisioning import hostcheck
from apex.wiring import contexts

NAME = "doctor"
SUMMARY = "what the host has and what a machine needs"


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: no runtime root to examine",
        )
    return context.root


def run(request: commandspecs.Request) -> commandspecs.Reply:
    _parser().parse_args(list(request.arguments))
    root = _root(request.context)
    ports = request.context.bundle(root)
    report = hostcheck.examine(ports, request.context.settings, root)
    problems = report.problems()
    if not problems:
        return commandspecs.Reply(document=report.document())
    return commandspecs.Reply(
        document=report.document(),
        narrative="".join(f"{problem}\n" for problem in problems),
        exit_code=errors.Refusal.exit_code,
    )


RECIPES = (commandspecs.Recipe("doctor", (), (NAME,)),)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

"""Install the local git hooks that hand every decision to the rules."""

from __future__ import annotations

import argparse

from apex.cli import commands, commandspecs, hookinstall

NAME = "hooks"
SUMMARY = "install the local git hooks that answer to the repository rules"


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)


def run(request: commandspecs.Request) -> commandspecs.Reply:
    _parser().parse_args(list(request.arguments))
    processes, filesystem = request.context.repository_ports()
    written = hookinstall.install(processes, filesystem, request.context.repository.path)
    return commandspecs.Reply(
        document={"installed": [str(item) for item in written], "entry": hookinstall.ENTRY},
        narrative="Local Git hooks installed\n",
    )


RECIPES = (commandspecs.Recipe("hooks", (), (NAME,)),)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

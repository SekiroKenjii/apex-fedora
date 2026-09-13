"""Bring every reviewed source into the runtime root, each checked against its pin."""

from __future__ import annotations

import argparse

from apex.cli import commands, commandspecs
from apex.config import sourcepins
from apex.kernel import encoding, errors, refusals, safepaths
from apex.trust import acquiring
from apex.wiring import contexts

NAME = "sources"
SUMMARY = "fetch the reviewed sources into the runtime root, or confirm they are held"


def _parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: no runtime root to fetch into",
        )
    return context.root


def document(acquired: acquiring.Acquisition) -> encoding.Document:
    return {
        "sources": [
            {
                "name": item.name,
                "filename": item.filename,
                "sha256": item.digest.hex,
                "fetched": item.fetched,
            }
            for item in acquired.sources
        ],
        "lock_record": acquired.lock_record.hex,
    }


def run(request: commandspecs.Request) -> commandspecs.Reply:
    _parser().parse_args(list(request.arguments))
    root = _root(request.context)
    ports = request.context.bundle(root)
    reviewed = sourcepins.load(request.context.repository)
    return commandspecs.Reply(
        document=document(acquiring.acquire(ports, reviewed=reviewed, root=root))
    )


RECIPES = (commandspecs.Recipe(NAME, (), (NAME,)),)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

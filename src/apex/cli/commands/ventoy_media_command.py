"""Prepare the Ventoy medium in the running builder from the inputs the operator names."""

from __future__ import annotations

import argparse
from pathlib import Path

from apex.cli import commands, commandspecs, verifyinputs
from apex.composition import keys as composition_keys
from apex.kernel import encoding, errors
from apex.model import machines
from apex.pipeline import runner
from apex.verification import ventoymedia, verifykeys
from apex.verification.recipes import ventoy_media_recipe

NAME = "ventoy-media"
SUMMARY = "prepare file-backed Ventoy media in the builder from reviewed, verified inputs"
OPTIONS = ("live-output", "ubuntu", "trusted-key", "checksums", "signature", "keyring")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    for option in OPTIONS:
        parser.add_argument(f"--{option}", required=True, type=Path)
    return parser


def _document(outcome: runner.Outcome) -> encoding.Document:
    run = outcome.facts.get(composition_keys.RUN_ID)
    medium = outcome.facts.get(verifykeys.MEDIA)
    return {
        "succeeded": outcome.succeeded,
        "run": None if run is None else str(run),
        "medium": None if medium is None else str(medium),
        "refusal": None if outcome.refusal is None else str(outcome.refusal),
        "detail": outcome.detail,
        "facts": list(outcome.facts.names()),
    }


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    inputs = verifyinputs.gather(
        request.context, role=machines.VmRole.BUILDER, asked=verifyinputs.Asked()
    )
    outcome = ventoy_media_recipe.prepare(
        inputs.ports,
        builder=inputs.guest,
        wheel=inputs.wheel,
        root=inputs.root,
        repository=inputs.repository,
        inputs=ventoymedia.Inputs(
            live_output=arguments.live_output,
            ubuntu=arguments.ubuntu,
            trusted_key=arguments.trusted_key,
            checksums=arguments.checksums,
            signature=arguments.signature,
            keyring=arguments.keyring,
        ),
    )
    if outcome.succeeded:
        return commandspecs.Reply(document=_document(outcome))
    exit_code = errors.Refusal.exit_code if outcome.refusal is not None else 1
    return commandspecs.Reply(
        document=_document(outcome), narrative=f"{NAME}: {outcome.detail}\n", exit_code=exit_code
    )


RECIPES = (
    commandspecs.Recipe(
        NAME, tuple(option.replace("-", "_") for option in OPTIONS),
        (NAME, *(
            word for option in OPTIONS
            for word in (f"--{option}", "{{" + option.replace("-", "_") + "}}")
        )),
    ),
)

commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=RECIPES))

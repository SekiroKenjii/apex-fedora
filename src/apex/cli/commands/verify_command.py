"""Run a verification recipe against the machine that is running, and record what it proves.

Everything the recipe needs is taken from the runtime root: the lease says which machine
runs, where its monitor is and what witness its launcher vouched for; the wheel the guest
runs is the one placed beside the store; the candidate is the frozen one; the recorder
opens the store for this run. Each recipe names the role it runs against: a disposable
test machine for the desktop and live recipes, whose guest account comes from `--user` or
from the credentials file a keyboard login needs; the isolated builder for the fingerprint
recipe, whose account is the builder's own and whose target is the build named by `--build`.
A live medium has no ssh, so `--serial` reaches its rescue shell over the serial socket the
machine was started with, as root unless `--user` says otherwise; the older live check's
case names are accepted as spellings of the recipes that took them over.
"""

from __future__ import annotations

import argparse
import dataclasses
from collections.abc import Callable
from pathlib import Path

from apex.cli import commands, commandspecs, verifyinputs
from apex.kernel import encoding, errors, refusals
from apex.model import machines
from apex.pipeline import runner
from apex.verification.recipes import (
    desktop_render_recipe,
    desktop_theme_recipe,
    fingerprint_cleanup_recipe,
    installer_trust_recipe,
    live_lock_recipe,
    live_observe_recipe,
    live_protection_recipe,
    ventoy_observe_recipe,
)

NAME = "verify"
SUMMARY = "run a verification recipe against the running machine and record its result"
LIVE_PROTECTION = "live-protection"
DESKTOP_THEME = "desktop-theme"
DESKTOP_RENDER = "desktop-render"
FINGERPRINT_CLEANUP = "fingerprint-cleanup"
INSTALLER_TRUST = "installer-trust"
LIVE_OBSERVE = "live-observe"
VENTOY_OBSERVE = "ventoy-observe"
LIVE_LOCK = "live-lock"
RECIPES = (
    LIVE_PROTECTION, DESKTOP_THEME, DESKTOP_RENDER, FINGERPRINT_CLEANUP, INSTALLER_TRUST,
    LIVE_OBSERVE, VENTOY_OBSERVE, LIVE_LOCK,
)
CASES: dict[str, str] = {
    "observe": LIVE_OBSERVE,
    "write-denial": LIVE_PROTECTION,
    "usb-write-denial": LIVE_PROTECTION,
    "lock-fault": LIVE_LOCK,
}
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    parser.add_argument("recipe", choices=(*RECIPES, *CASES))
    parser.add_argument("--user", help="the guest account the shell opens as")
    parser.add_argument(
        "--serial", action="store_true",
        help="reach the guest's rescue shell over the machine's serial socket, not ssh",
    )
    parser.add_argument(
        "--credentials", type=Path,
        help="the disposable account's credentials file, inside the runtime root",
    )
    parser.add_argument("--build", help="the completed image build a builder recipe tests")
    return parser


@dataclasses.dataclass(frozen=True, slots=True)
class Recipe:
    role: machines.VmRole
    run: Callable[[verifyinputs.Inputs], runner.Outcome]


def _live_protection(inputs: verifyinputs.Inputs) -> runner.Outcome:
    return live_protection_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel,
        candidate=verifyinputs.required_candidate(inputs), witness=inputs.lease.intent.witness,
        recorder=inputs.recorder,
    )


def _desktop_theme(inputs: verifyinputs.Inputs) -> runner.Outcome:
    return desktop_theme_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel,
        candidate=verifyinputs.required_candidate(inputs), witness=inputs.lease.intent.witness,
        recorder=inputs.recorder, monitor=inputs.lease.intent.monitor, root=inputs.root,
    )


def _desktop_render(inputs: verifyinputs.Inputs) -> runner.Outcome:
    if inputs.credentials is None:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"{DESKTOP_RENDER} logs in with a password",
            remedy="name the account's credentials file with --credentials",
        )
    return desktop_render_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel,
        candidate=verifyinputs.required_candidate(inputs), witness=inputs.lease.intent.witness,
        recorder=inputs.recorder, monitor=inputs.lease.intent.monitor,
        credentials=inputs.credentials, root=inputs.root,
    )


def _fingerprint_cleanup(inputs: verifyinputs.Inputs) -> runner.Outcome:
    if inputs.parent is None:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"{FINGERPRINT_CLEANUP} tests the packages of one completed image build",
            remedy="name that build with --build",
        )
    return fingerprint_cleanup_recipe.verify(
        inputs.ports, builder=inputs.guest, wheel=inputs.wheel, parent=inputs.parent,
        witness=inputs.lease.intent.witness, recorder=inputs.recorder, root=inputs.root,
        repository=inputs.repository,
    )


def _installer_trust(inputs: verifyinputs.Inputs) -> runner.Outcome:
    return installer_trust_recipe.verify(
        inputs.ports, builder=inputs.guest, wheel=inputs.wheel, root=inputs.root
    )


def _live_observe(inputs: verifyinputs.Inputs) -> runner.Outcome:
    return live_observe_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel, root=inputs.root
    )


def _ventoy_observe(inputs: verifyinputs.Inputs) -> runner.Outcome:
    return ventoy_observe_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel, root=inputs.root
    )


def _live_lock(inputs: verifyinputs.Inputs) -> runner.Outcome:
    return live_lock_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel, root=inputs.root
    )


RUNNERS: dict[str, Recipe] = {
    LIVE_PROTECTION: Recipe(machines.VmRole.TEST, _live_protection),
    DESKTOP_THEME: Recipe(machines.VmRole.TEST, _desktop_theme),
    DESKTOP_RENDER: Recipe(machines.VmRole.TEST, _desktop_render),
    FINGERPRINT_CLEANUP: Recipe(machines.VmRole.BUILDER, _fingerprint_cleanup),
    INSTALLER_TRUST: Recipe(machines.VmRole.BUILDER, _installer_trust),
    LIVE_OBSERVE: Recipe(machines.VmRole.TEST, _live_observe),
    VENTOY_OBSERVE: Recipe(machines.VmRole.TEST, _ventoy_observe),
    LIVE_LOCK: Recipe(machines.VmRole.TEST, _live_lock),
}


def _document(outcome: runner.Outcome) -> encoding.Document:
    return {
        "succeeded": outcome.succeeded,
        "attested": [str(check) for check in outcome.attested],
        "not_tested": [str(check) for check in outcome.not_tested],
        "refusal": None if outcome.refusal is None else str(outcome.refusal),
        "detail": outcome.detail,
        "facts": list(outcome.facts.names()),
    }


def run(request: commandspecs.Request) -> commandspecs.Reply:
    arguments = _parser().parse_args(list(request.arguments))
    name = str(CASES.get(arguments.recipe, arguments.recipe))
    recipe = RUNNERS[name]
    asked = verifyinputs.Asked(
        user=arguments.user, credentials=arguments.credentials, build=arguments.build,
        serial=arguments.serial,
    )
    inputs = verifyinputs.gather(request.context, role=recipe.role, asked=asked)
    outcome = recipe.run(inputs)
    if outcome.succeeded:
        return commandspecs.Reply(document=_document(outcome))
    exit_code = errors.Refusal.exit_code if outcome.refusal is not None else 1
    return commandspecs.Reply(
        document=_document(outcome), narrative=f"{name}: {outcome.detail}\n", exit_code=exit_code
    )


JUST_RECIPES = (
    commandspecs.Recipe(
        "verify-live-protection", ("user",), (NAME, LIVE_PROTECTION, "--user", "{{user}}")
    ),
    commandspecs.Recipe(
        "verify-desktop-theme", ("user",), (NAME, DESKTOP_THEME, "--user", "{{user}}")
    ),
    commandspecs.Recipe(
        "verify-desktop-render", ("credentials",),
        (NAME, DESKTOP_RENDER, "--credentials", "{{credentials}}"),
    ),
    commandspecs.Recipe(
        "test-fingerprint", ("build_id",), (NAME, FINGERPRINT_CLEANUP, "--build", "{{build_id}}")
    ),
    commandspecs.Recipe("test-installer-trust", (), (NAME, INSTALLER_TRUST)),
    commandspecs.Recipe("test-live-check", ("case",), (NAME, "{{case}}", "--serial")),
)

commands.declare(
    commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=JUST_RECIPES)
)

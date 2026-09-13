"""Run a verification recipe against the machine that is running, and record what it proves.

Everything the recipe needs is taken from the runtime root: the lease says which machine
runs, where its monitor is and what witness its launcher vouched for; the wheel the guest
runs is the one placed beside the store; the candidate is the frozen one; the recorder
opens the store for this run. Each recipe names the role it runs against: a disposable
test machine for the desktop and live recipes, whose guest account comes from `--user` or
from the credentials file a keyboard login needs; the isolated builder for the fingerprint
recipes, whose account is the builder's own and whose target is the build named by `--build`,
an image build for the cleanup fault and a package build for the smoke and dialog tests.
A live medium has no ssh, so `--serial` reaches its rescue shell over the serial socket the
machine was started with, as root unless `--user` says otherwise; the older live check's
case names are accepted as spellings of the recipes that took them over. The installer
payload fault names its case with `--case`, and only the wrong-key case takes a key.
"""

from __future__ import annotations

import argparse
import dataclasses
from collections.abc import Callable
from pathlib import Path

from apex.cli import commands, commandspecs, verifyinputs
from apex.kernel import encoding, errors, identifiers, refusals
from apex.model import machines
from apex.pipeline import runner
from apex.verification import installerfault
from apex.verification.recipes import (
    desktop_render_recipe,
    desktop_theme_recipe,
    fingerprint_cleanup_recipe,
    fingerprint_gtk_recipe,
    fingerprint_rpms_test_recipe,
    installer_diagnostics_recipe,
    installer_payload_recipe,
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
INSTALLER_PAYLOAD = "installer-payload"
INSTALLER_DIAGNOSTICS = "installer-diagnostics"
FINGERPRINT_RPMS = "fingerprint-rpms"
FINGERPRINT_GTK = "fingerprint-gtk"
RECIPES = (
    LIVE_PROTECTION, DESKTOP_THEME, DESKTOP_RENDER, FINGERPRINT_CLEANUP, INSTALLER_TRUST,
    LIVE_OBSERVE, VENTOY_OBSERVE, LIVE_LOCK, INSTALLER_PAYLOAD, INSTALLER_DIAGNOSTICS,
    FINGERPRINT_RPMS, FINGERPRINT_GTK,
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
    parser.add_argument(
        "--case", choices=installerfault.CASES, help="the damage the installer payload fault does"
    )
    parser.add_argument(
        "--wrong-key", type=Path, help="a public key that is not the payload's, wrong-key only"
    )
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


def _built_packages(inputs: verifyinputs.Inputs, name: str) -> identifiers.BuildId:
    if inputs.parent is None:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"{name} tests the packages of one completed package build",
            remedy="name that build with --build",
        )
    return inputs.parent


def _fingerprint_rpms(inputs: verifyinputs.Inputs) -> runner.Outcome:
    return fingerprint_rpms_test_recipe.verify(
        inputs.ports, builder=inputs.guest, parent=_built_packages(inputs, FINGERPRINT_RPMS),
        root=inputs.root, repository=inputs.repository,
    )


def _fingerprint_gtk(inputs: verifyinputs.Inputs) -> runner.Outcome:
    return fingerprint_gtk_recipe.verify(
        inputs.ports, builder=inputs.guest, parent=_built_packages(inputs, FINGERPRINT_GTK),
        root=inputs.root, repository=inputs.repository,
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


def _installer_payload(inputs: verifyinputs.Inputs) -> runner.Outcome:
    if inputs.case is None:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"{INSTALLER_PAYLOAD} damages the payload in one named way",
            remedy=f"name it with --case, one of {', '.join(installerfault.CASES)}",
        )
    return installer_payload_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel, root=inputs.root,
        run_directory=inputs.lease.intent.run_directory, process=inputs.lease.identity.process,
        case=inputs.case, wrong_key=inputs.wrong_key,
    )


def _installer_diagnostics(inputs: verifyinputs.Inputs) -> runner.Outcome:
    return installer_diagnostics_recipe.verify(
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
    INSTALLER_PAYLOAD: Recipe(machines.VmRole.TEST, _installer_payload),
    INSTALLER_DIAGNOSTICS: Recipe(machines.VmRole.TEST, _installer_diagnostics),
    FINGERPRINT_RPMS: Recipe(machines.VmRole.BUILDER, _fingerprint_rpms),
    FINGERPRINT_GTK: Recipe(machines.VmRole.BUILDER, _fingerprint_gtk),
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
    if name != INSTALLER_PAYLOAD and (arguments.case or arguments.wrong_key):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"{name} takes neither --case nor --wrong-key",
            remedy=f"those name the {INSTALLER_PAYLOAD} fault's case",
        )
    asked = verifyinputs.Asked(
        user=arguments.user, credentials=arguments.credentials, build=arguments.build,
        serial=arguments.serial, case=arguments.case, wrong_key=arguments.wrong_key,
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
    commandspecs.Recipe(
        "test-installer-fault", ("case",),
        (NAME, INSTALLER_PAYLOAD, "--case", "{{case}}", "--serial"),
    ),
    commandspecs.Recipe(
        "test-installer-wrong-key", ("public_key",),
        (NAME, INSTALLER_PAYLOAD, "--case", installerfault.KEY_CASE, "--wrong-key",
         "{{public_key}}", "--serial"),
    ),
    commandspecs.Recipe("installer-logs-prepare", (), (NAME, INSTALLER_DIAGNOSTICS, "--serial")),
    commandspecs.Recipe(
        "test-fingerprint-rpms", ("build_id",), (NAME, FINGERPRINT_RPMS, "--build", "{{build_id}}")
    ),
    commandspecs.Recipe(
        "test-fingerprint-gtk", ("build_id",), (NAME, FINGERPRINT_GTK, "--build", "{{build_id}}")
    ),
)

commands.declare(
    commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=JUST_RECIPES)
)

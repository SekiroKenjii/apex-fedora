"""Run a verification recipe against the machine that is running, and record what it proves.

Everything the recipe needs is taken from the runtime root: the lease says which machine
runs, where its monitor is and what witness its launcher vouched for; the wheel the guest
runs is the one placed beside the store; the candidate is the frozen one; the recorder
opens the store for this run. Each recipe names the role it runs against: a disposable
test machine for the desktop and live recipes, whose guest account comes from `--user` or
from the credentials file a keyboard login needs; the isolated builder for the fingerprint
recipe, whose account is the builder's own and whose target is the build named by `--build`.
"""

from __future__ import annotations

import argparse
import dataclasses
from collections.abc import Callable
from pathlib import Path

from apex.cli import commands, commandspecs
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.model import machines, runtimestate
from apex.pipeline import runner
from apex.ports import guestshell, portset
from apex.provisioning import launching, leases
from apex.verification import recording, testaccess
from apex.verification.recipes import (
    desktop_render_recipe,
    desktop_theme_recipe,
    fingerprint_cleanup_recipe,
    live_protection_recipe,
)
from apex.wiring import contexts

NAME = "verify"
SUMMARY = "run a verification recipe against the running machine and record its result"
LIVE_PROTECTION = "live-protection"
DESKTOP_THEME = "desktop-theme"
DESKTOP_RENDER = "desktop-render"
FINGERPRINT_CLEANUP = "fingerprint-cleanup"
RECIPES = (LIVE_PROTECTION, DESKTOP_THEME, DESKTOP_RENDER, FINGERPRINT_CLEANUP)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    parser.add_argument("recipe", choices=RECIPES)
    parser.add_argument("--user", help="the guest account the shell opens as")
    parser.add_argument(
        "--credentials", type=Path,
        help="the disposable account's credentials file, inside the runtime root",
    )
    parser.add_argument("--build", help="the completed image build a builder recipe tests")
    return parser


@dataclasses.dataclass(frozen=True, slots=True)
class Inputs:
    ports: portset.HostPorts
    guest: guestshell.GuestTarget
    wheel: safepaths.SafePath
    candidate: identifiers.Digest | None
    lease: leases.MachineLease
    recorder: recording.Recorder
    root: safepaths.RuntimeRoot
    repository: safepaths.SourceRoot
    credentials: testaccess.Credentials | None
    parent: identifiers.BuildId | None


@dataclasses.dataclass(frozen=True, slots=True)
class Recipe:
    role: machines.VmRole
    run: Callable[[Inputs], runner.Outcome]


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: no runtime root to verify from",
        )
    return context.root


def _running_machine(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, role: machines.VmRole
) -> leases.MachineLease:
    lease = launching.current(ports, root=root)
    if lease is None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_NOT_RUNNING,
            subject="no machine is running",
            remedy=f"start the {role} machine first",
        )
    if lease.intent.role is role:
        return lease
    if role is machines.VmRole.TEST:
        raise errors.Refusal(
            refusals.RefusalReason.NOT_A_DISPOSABLE_MACHINE,
            subject=f"a {lease.intent.role} machine is running",
            remedy="this recipe mutates its guest and runs only against a test machine",
        )
    raise errors.Refusal(
        refusals.RefusalReason.MACHINE_ROLE_MISMATCH,
        subject=f"a {lease.intent.role} machine is running",
        remedy=f"this recipe runs in the isolated {role}",
    )


def _present(root: safepaths.RuntimeRoot, name: str, *, remedy: str) -> safepaths.SafePath:
    candidate = root.child(name)
    if not candidate.path.is_file():
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE, subject=f"{candidate}: {remedy}"
        )
    return safepaths.SafePath.regular_file(candidate.path, within=root)


def _candidate(root: safepaths.RuntimeRoot) -> identifiers.Digest:
    document = root.child(runtimestate.CANDIDATE_NAME)
    if not document.path.is_file():
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject=f"{document}: select a candidate before verifying",
        )
    return runtimestate.read_candidate(document.path).digest


def _required_candidate(inputs: Inputs) -> identifiers.Digest:
    if inputs.candidate is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE,
            subject="no candidate was selected for a test machine recipe",
        )
    return inputs.candidate


def _live_protection(inputs: Inputs) -> runner.Outcome:
    return live_protection_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel,
        candidate=_required_candidate(inputs), witness=inputs.lease.intent.witness,
        recorder=inputs.recorder,
    )


def _desktop_theme(inputs: Inputs) -> runner.Outcome:
    return desktop_theme_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel,
        candidate=_required_candidate(inputs), witness=inputs.lease.intent.witness,
        recorder=inputs.recorder, monitor=inputs.lease.intent.monitor, root=inputs.root,
    )


def _desktop_render(inputs: Inputs) -> runner.Outcome:
    if inputs.credentials is None:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"{DESKTOP_RENDER} logs in with a password",
            remedy="name the account's credentials file with --credentials",
        )
    return desktop_render_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel,
        candidate=_required_candidate(inputs), witness=inputs.lease.intent.witness,
        recorder=inputs.recorder, monitor=inputs.lease.intent.monitor,
        credentials=inputs.credentials, root=inputs.root,
    )


def _fingerprint_cleanup(inputs: Inputs) -> runner.Outcome:
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


RUNNERS: dict[str, Recipe] = {
    LIVE_PROTECTION: Recipe(machines.VmRole.TEST, _live_protection),
    DESKTOP_THEME: Recipe(machines.VmRole.TEST, _desktop_theme),
    DESKTOP_RENDER: Recipe(machines.VmRole.TEST, _desktop_render),
    FINGERPRINT_CLEANUP: Recipe(machines.VmRole.BUILDER, _fingerprint_cleanup),
}


def _credentials(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, path: Path | None
) -> testaccess.Credentials | None:
    if path is None:
        return None
    return testaccess.read(ports.files, safepaths.SafePath.regular_file(path, within=root))


def _guest(
    root: safepaths.RuntimeRoot,
    role: machines.VmRole,
    arguments: argparse.Namespace,
    credentials: testaccess.Credentials | None,
) -> guestshell.GuestTarget:
    """The account and key a recipe reaches its guest with, fixed for the builder."""
    if role is machines.VmRole.BUILDER:
        if arguments.user is not None or credentials is not None:
            raise errors.Refusal(
                refusals.RefusalReason.REQUEST_MALFORMED,
                subject="a builder recipe takes neither --user nor --credentials",
                remedy="the builder's account and key are the runtime root's own",
            )
        return guestshell.GuestTarget(
            user=defaults.BUILDER_USER,
            port=defaults.BUILDER_SSH_PORT,
            key=_present(root, defaults.BUILDER_KEY_NAME, remedy="prepare the builder first"),
            known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
        )
    return guestshell.GuestTarget(
        user=_account(arguments.user, credentials),
        port=defaults.GUEST_SSH_PORT,
        key=_present(root, defaults.GUEST_KEY_NAME, remedy="place the guest key beside the store"),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def _parent(value: str | None) -> identifiers.BuildId | None:
    return None if value is None else identifiers.BuildId.parse(value)


def _account(user: str | None, credentials: testaccess.Credentials | None) -> str:
    """The guest account: the one named, the one the credentials name, and never two."""
    if credentials is not None and user not in (None, credentials.user):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"--user {user} but the credentials name {credentials.user}",
            remedy="name one account",
        )
    named = user if credentials is None else credentials.user
    if named is None:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject="no guest account",
            remedy="name it with --user or --credentials",
        )
    return named


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
    root = _root(request.context)
    ports = request.context.bundle(root)
    recipe = RUNNERS[arguments.recipe]
    lease = _running_machine(ports, root, recipe.role)
    credentials = _credentials(ports, root, arguments.credentials)
    inputs = Inputs(
        ports=ports,
        guest=_guest(root, recipe.role, arguments, credentials),
        wheel=_present(
            root, defaults.AGENT_WHEEL_NAME, remedy="build the agent wheel into the root"
        ),
        candidate=_candidate(root) if recipe.role is machines.VmRole.TEST else None,
        lease=lease,
        recorder=recording.Recorder.open(
            root, filesystem=ports.files, identities=ports.identities, clock=ports.clock
        ),
        root=root,
        repository=request.context.repository,
        credentials=credentials,
        parent=_parent(arguments.build),
    )
    outcome = recipe.run(inputs)
    if outcome.succeeded:
        return commandspecs.Reply(document=_document(outcome))
    exit_code = errors.Refusal.exit_code if outcome.refusal is not None else 1
    return commandspecs.Reply(
        document=_document(outcome),
        narrative=f"{arguments.recipe}: {outcome.detail}\n",
        exit_code=exit_code,
    )


commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run))

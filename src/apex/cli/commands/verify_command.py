"""Run a verification recipe against the machine that is running, and record what it proves.

Everything the recipe needs is taken from the runtime root: the lease says which machine
runs, where its monitor is and what witness its launcher vouched for; the wheel the guest
runs is the one placed beside the store; the candidate is the frozen one; the recorder
opens the store for this run. A builder is refused, since a recipe mutates its guest. The
guest account comes from `--user`, or from the credentials file a keyboard login needs,
which also carries the password that is typed and never rendered.
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
    live_protection_recipe,
)
from apex.wiring import contexts

NAME = "verify"
SUMMARY = "run a verification recipe against the running test machine and record its result"
LIVE_PROTECTION = "live-protection"
DESKTOP_THEME = "desktop-theme"
DESKTOP_RENDER = "desktop-render"
RECIPES = (LIVE_PROTECTION, DESKTOP_THEME, DESKTOP_RENDER)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    parser.add_argument("recipe", choices=RECIPES)
    parser.add_argument("--user", help="the guest account the shell opens as")
    parser.add_argument(
        "--credentials", type=Path,
        help="the disposable account's credentials file, inside the runtime root",
    )
    return parser


@dataclasses.dataclass(frozen=True, slots=True)
class Inputs:
    ports: portset.HostPorts
    guest: guestshell.GuestTarget
    wheel: safepaths.SafePath
    candidate: identifiers.Digest
    lease: leases.MachineLease
    recorder: recording.Recorder
    root: safepaths.RuntimeRoot
    credentials: testaccess.Credentials | None


def _root(context: contexts.Context) -> safepaths.RuntimeRoot:
    if context.root is None:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.PATH_NOT_A_DIRECTORY,
            subject=f"{context.settings.runtime_root}: no runtime root to verify from",
        )
    return context.root


def _running_test_machine(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> leases.MachineLease:
    lease = launching.current(ports, root=root)
    if lease is None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_NOT_RUNNING,
            subject="no machine is running",
            remedy="start a disposable test machine first",
        )
    if lease.intent.role is not machines.VmRole.TEST:
        raise errors.Refusal(
            refusals.RefusalReason.NOT_A_DISPOSABLE_MACHINE,
            subject=f"a {lease.intent.role} machine is running",
            remedy="verification mutates its guest and runs only against a test machine",
        )
    return lease


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


Recipe = Callable[[Inputs], runner.Outcome]


def _live_protection(inputs: Inputs) -> runner.Outcome:
    return live_protection_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel, candidate=inputs.candidate,
        witness=inputs.lease.intent.witness, recorder=inputs.recorder,
    )


def _desktop_theme(inputs: Inputs) -> runner.Outcome:
    return desktop_theme_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel, candidate=inputs.candidate,
        witness=inputs.lease.intent.witness, recorder=inputs.recorder,
        monitor=inputs.lease.intent.monitor, root=inputs.root,
    )


def _desktop_render(inputs: Inputs) -> runner.Outcome:
    if inputs.credentials is None:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"{DESKTOP_RENDER} logs in with a password",
            remedy="name the account's credentials file with --credentials",
        )
    return desktop_render_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel, candidate=inputs.candidate,
        witness=inputs.lease.intent.witness, recorder=inputs.recorder,
        monitor=inputs.lease.intent.monitor, credentials=inputs.credentials, root=inputs.root,
    )


RUNNERS: dict[str, Recipe] = {
    LIVE_PROTECTION: _live_protection,
    DESKTOP_THEME: _desktop_theme,
    DESKTOP_RENDER: _desktop_render,
}


def _credentials(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, path: Path | None
) -> testaccess.Credentials | None:
    if path is None:
        return None
    return testaccess.read(ports.files, safepaths.SafePath.regular_file(path, within=root))


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
    lease = _running_test_machine(ports, root)
    credentials = _credentials(ports, root, arguments.credentials)
    guest = guestshell.GuestTarget(
        user=_account(arguments.user, credentials),
        port=defaults.GUEST_SSH_PORT,
        key=_present(root, defaults.GUEST_KEY_NAME, remedy="place the guest key beside the store"),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )
    inputs = Inputs(
        ports=ports,
        guest=guest,
        wheel=_present(
            root, defaults.AGENT_WHEEL_NAME, remedy="build the agent wheel into the root"
        ),
        candidate=_candidate(root),
        lease=lease,
        recorder=recording.Recorder.open(
            root, filesystem=ports.files, identities=ports.identities, clock=ports.clock
        ),
        root=root,
        credentials=credentials,
    )
    outcome = RUNNERS[arguments.recipe](inputs)
    if outcome.succeeded:
        return commandspecs.Reply(document=_document(outcome))
    exit_code = errors.Refusal.exit_code if outcome.refusal is not None else 1
    return commandspecs.Reply(
        document=_document(outcome),
        narrative=f"{arguments.recipe}: {outcome.detail}\n",
        exit_code=exit_code,
    )


commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run))

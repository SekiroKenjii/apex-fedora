"""Run a verification recipe against the machine that is running, and record what it proves.

Everything the recipe needs is taken from the runtime root: the lease says which machine
runs, where its monitor is and what witness its launcher vouched for; the wheel the guest
runs is the one placed beside the store; the candidate is the frozen one; the recorder
opens the store for this run. A builder is refused, since a recipe mutates its guest.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable

from apex.cli import commands, commandspecs
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers, refusals, safepaths
from apex.model import machines, runtimestate
from apex.pipeline import runner
from apex.ports import guestshell, portset
from apex.provisioning import launching, leases
from apex.verification import recording
from apex.verification.recipes import desktop_theme_recipe, live_protection_recipe
from apex.wiring import contexts

NAME = "verify"
SUMMARY = "run a verification recipe against the running test machine and record its result"
LIVE_PROTECTION = "live-protection"
DESKTOP_THEME = "desktop-theme"
RECIPES = (LIVE_PROTECTION, DESKTOP_THEME)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    parser.add_argument("recipe", choices=RECIPES)
    parser.add_argument("--user", required=True, help="the guest account the shell opens as")
    return parser


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


Recipe = Callable[
    [portset.HostPorts, guestshell.GuestTarget, safepaths.SafePath, identifiers.Digest,
     leases.MachineLease, recording.Recorder, safepaths.RuntimeRoot],
    runner.Outcome,
]


def _live_protection(
    ports: portset.HostPorts,
    guest: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    candidate: identifiers.Digest,
    lease: leases.MachineLease,
    recorder: recording.Recorder,
    root: safepaths.RuntimeRoot,  # noqa: ARG001
) -> runner.Outcome:
    return live_protection_recipe.verify(
        ports, guest=guest, wheel=wheel, candidate=candidate, witness=lease.intent.witness,
        recorder=recorder,
    )


def _desktop_theme(
    ports: portset.HostPorts,
    guest: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    candidate: identifiers.Digest,
    lease: leases.MachineLease,
    recorder: recording.Recorder,
    root: safepaths.RuntimeRoot,
) -> runner.Outcome:
    return desktop_theme_recipe.verify(
        ports, guest=guest, wheel=wheel, candidate=candidate, witness=lease.intent.witness,
        recorder=recorder, monitor=lease.intent.monitor, root=root,
    )


RUNNERS: dict[str, Recipe] = {LIVE_PROTECTION: _live_protection, DESKTOP_THEME: _desktop_theme}


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
    guest = guestshell.GuestTarget(
        user=arguments.user,
        port=defaults.GUEST_SSH_PORT,
        key=_present(root, defaults.GUEST_KEY_NAME, remedy="place the guest key beside the store"),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )
    wheel = _present(root, defaults.AGENT_WHEEL_NAME, remedy="build the agent wheel into the root")
    candidate = _candidate(root)
    recorder = recording.Recorder.open(
        root, filesystem=ports.files, identities=ports.identities, clock=ports.clock
    )
    outcome = RUNNERS[arguments.recipe](ports, guest, wheel, candidate, lease, recorder, root)
    if outcome.succeeded:
        return commandspecs.Reply(document=_document(outcome))
    exit_code = errors.Refusal.exit_code if outcome.refusal is not None else 1
    return commandspecs.Reply(
        document=_document(outcome),
        narrative=f"{arguments.recipe}: {outcome.detail}\n",
        exit_code=exit_code,
    )


commands.declare(commandspecs.Command(name=NAME, summary=SUMMARY, run=run))

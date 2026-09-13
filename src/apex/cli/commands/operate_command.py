"""Operate on the disposable guest with a completed update fixture, as the older tools did.

Three families of operation, each the older tool's actions under its own name: the A/B
update operations, the recovery diagnostics and the initramfs fault. Every one reaches the
test machine as the disposable account, from the access directory the fixture's build left,
and runs its privileged steps through that account's password. The fixture is named by its
run or its directory; an injection names the inspection it was reviewed against.
"""

from __future__ import annotations

import argparse
import dataclasses
from collections.abc import Callable
from pathlib import Path

from apex.cli import commands, commandspecs, verifyinputs
from apex.config import defaults
from apex.kernel import encoding, errors, refusals, safepaths
from apex.model import machines
from apex.pipeline import runner
from apex.verification import (
    initramfsops,
    recoveryops,
    testaccess,
    updatefixtures,
    updateops,
    verifykeys,
)
from apex.verification.recipes import (
    initramfs_operation_recipe,
    recovery_operation_recipe,
    update_check_recipe,
    update_operation_recipe,
)

NAME = "operate"
SUMMARY = "run an update, recovery or initramfs operation on the disposable guest"
UPDATE = updateops.NAME
RECOVERY = recoveryops.NAME
INITRAMFS = initramfsops.NAME
FAMILIES: dict[str, tuple[str, ...]] = {
    UPDATE: updateops.ACTIONS, RECOVERY: recoveryops.ACTIONS, INITRAMFS: initramfsops.ACTIONS,
}
ACTION = "action"
FIXTURE = "fixture"
ACCESS = "access"
INSPECTION = "inspection"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=f"apex {NAME}", description=SUMMARY)
    parser.add_argument("family", choices=tuple(FAMILIES))
    parser.add_argument(f"--{ACTION}", required=True, help="the older tool's action name")
    parser.add_argument(
        f"--{FIXTURE}", required=True,
        help="the completed update fixture, by run identifier or export directory",
    )
    parser.add_argument(
        f"--{ACCESS}", type=Path, required=True,
        help="the disposable account's access directory, inside the runtime root",
    )
    parser.add_argument(
        f"--{INSPECTION}", type=Path,
        help="the reviewed inspection report an initramfs injection is bound to",
    )
    return parser


@dataclasses.dataclass(frozen=True, slots=True)
class Request:
    family: str
    action: str
    fixture: str
    access: Path
    inspection: Path | None

    @classmethod
    def parse(cls, arguments: argparse.Namespace) -> Request:
        family, action = str(arguments.family), str(arguments.action)
        if action not in FAMILIES[family]:
            raise errors.Refusal(
                refusals.RefusalReason.REQUEST_MALFORMED,
                subject=f"{family} has no action {action}",
                remedy=f"one of {', '.join(FAMILIES[family])}",
            )
        injecting = family == INITRAMFS and action == initramfsops.INJECT
        if (arguments.inspection is not None) != injecting:
            raise errors.Refusal(
                refusals.RefusalReason.REQUEST_MALFORMED,
                subject=f"--{INSPECTION} belongs to the initramfs injection alone",
                remedy="name the reviewed inspection there and nowhere else",
            )
        return cls(
            family=family, action=action, fixture=str(arguments.fixture),
            access=arguments.access, inspection=arguments.inspection,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Gathered:
    inputs: verifyinputs.Inputs
    located: updatefixtures.Located
    request: Request

    def credentials(self) -> testaccess.Credentials:
        if self.inputs.credentials is None:
            raise errors.InternalDefect("an access directory always yields credentials")
        return self.inputs.credentials

    def inspection(self) -> encoding.Document | None:
        if self.request.inspection is None:
            return None
        path = safepaths.SafePath.regular_file(self.request.inspection, within=self.inputs.root)
        try:
            return encoding.parse_object(
                self.inputs.ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)
            )
        except ValueError as malformed:
            raise errors.Refusal(
                refusals.RefusalReason.REQUEST_MALFORMED,
                subject=f"{path.path.name}: not an inspection report: {malformed}",
            ) from malformed


def _update(gathered: Gathered) -> runner.Outcome:
    inputs = gathered.inputs
    if gathered.request.action in updateops.CHECKS:
        return update_check_recipe.verify(
            inputs.ports, guest=inputs.guest, wheel=inputs.wheel, fixture=gathered.located,
            action=gathered.request.action, credentials=gathered.credentials(),
            process=inputs.lease.identity.process, monitor=inputs.lease.intent.monitor,
            root=inputs.root,
        )
    return update_operation_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel, fixture=gathered.located,
        action=gathered.request.action, credentials=gathered.credentials(),
        process=inputs.lease.identity.process, root=inputs.root,
    )


def _recovery(gathered: Gathered) -> runner.Outcome:
    inputs = gathered.inputs
    return recovery_operation_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel, fixture=gathered.located,
        action=gathered.request.action, credentials=gathered.credentials(),
        process=inputs.lease.identity.process, root=inputs.root,
    )


def _initramfs(gathered: Gathered) -> runner.Outcome:
    inputs = gathered.inputs
    return initramfs_operation_recipe.verify(
        inputs.ports, guest=inputs.guest, wheel=inputs.wheel, fixture=gathered.located,
        action=gathered.request.action, credentials=gathered.credentials(),
        process=inputs.lease.identity.process, inspection=gathered.inspection(),
        root=inputs.root,
    )


RUNNERS: dict[str, Callable[[Gathered], runner.Outcome]] = {
    UPDATE: _update, RECOVERY: _recovery, INITRAMFS: _initramfs,
}


def _document(outcome: runner.Outcome, family: str) -> encoding.Document:
    kept = verifykeys.retained_report(family)
    report = verifykeys.test_report(family)
    held = outcome.facts[report] if kept.name in outcome.facts.names() else None
    return {
        "succeeded": outcome.succeeded,
        "status": held.get("status") if isinstance(held, dict) else None,
        "report": str(outcome.facts[kept]) if kept.name in outcome.facts.names() else None,
        "refusal": None if outcome.refusal is None else str(outcome.refusal),
        "detail": outcome.detail,
    }


def run(request: commandspecs.Request) -> commandspecs.Reply:
    parsed = Request.parse(_parser().parse_args(list(request.arguments)))
    inputs = verifyinputs.gather(
        request.context, role=machines.VmRole.TEST, asked=verifyinputs.Asked(access=parsed.access)
    )
    located = updatefixtures.locate(inputs.ports, inputs.root, parsed.fixture)
    gathered = Gathered(inputs=inputs, located=located, request=parsed)
    outcome = RUNNERS[parsed.family](gathered)
    document = _document(outcome, parsed.family)
    if outcome.succeeded:
        return commandspecs.Reply(document=document)
    exit_code = errors.Refusal.exit_code if outcome.refusal is not None else 1
    return commandspecs.Reply(
        document=document, narrative=f"{parsed.family}: {outcome.detail}\n", exit_code=exit_code
    )


def _recipe(name: str, family: str, action: str | None, *extra: str) -> commandspecs.Recipe:
    operands = ("fixture", "access", *(("inspection",) if extra else ()))
    if action is None:
        operands = ("action", *operands)
    return commandspecs.Recipe(
        name, operands,
        (
            NAME, family, f"--{ACTION}", "{{action}}" if action is None else action,
            f"--{FIXTURE}", "{{fixture}}", f"--{ACCESS}", "{{access}}", *extra,
        ),
    )


JUST_RECIPES = (
    _recipe("test-update", UPDATE, None),
    _recipe("test-recovery", RECOVERY, None),
    _recipe("test-initramfs-inspect", INITRAMFS, initramfsops.INSPECT),
    _recipe(
        "test-initramfs-inject", INITRAMFS, initramfsops.INJECT,
        f"--{INSPECTION}", "{{inspection}}",
    ),
    _recipe("test-initramfs-rescue", INITRAMFS, initramfsops.RESCUE),
)

commands.declare(
    commandspecs.Command(name=NAME, summary=SUMMARY, run=run, recipes=JUST_RECIPES)
)

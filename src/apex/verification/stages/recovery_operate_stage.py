"""One recovery operation on the installed disposable guest, inspected before and after.

The installed configuration is verified by the unit that compares it with the image; every
other action reads the boot state first, does its one thing, and reads the state again,
except the reboot, which ends the shell and is judged by the request alone. The collection
carries the two-failure fallback judgement over the journal it brought back.
"""

from __future__ import annotations

from apex.composition import agentrun
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import encoding
from apex.verification import bootcstatus, gdmfallback, operating, recoveryops, verifykeys

INSPECT = "recovery.inspect"
INSTALLED = "recovery.installed"
OPERATE = "recovery.operate"
FIXTURE = "fixture.recovery"


def _installed(operation: operating.Operation) -> str:
    preset = recoveryops.require_preset(operation.located.preset)
    installed = operation.ask(INSTALLED, {
        "expected_digest": operation.image("a"), "config_sha256": preset,
    })
    operation.report["installed"] = installed
    return str(installed.get("status", operating.FAIL))


def _reboot(operation: operating.Operation, status: encoding.Document) -> str:
    recoveryops.require_staged(status, operation.image("b"))
    completed = agentrun.as_root(
        operation.context.ports, operation.context.facts[verifykeys.GUEST],
        "systemctl", "reboot",
        password=operation.context.facts[verifykeys.CREDENTIALS].password,
        deadline=defaults.PROBE_DEADLINE,
    )
    operation.report["reboot_request_returncode"] = completed.exit_code
    if completed.exit_code not in defaults.REBOOT_EXITS:
        raise bootcstatus.unexpected("guest reboot request failed")
    operation.report["scope"] = recoveryops.REBOOT_SCOPE
    return operating.PASS


def _change(operation: operating.Operation, before: encoding.Document) -> None:
    arguments: dict[str, encoding.JsonValue] = {
        "action": operation.action, "expected_digest": operation.image("a"),
        "run_id": str(operation.context.facts[composition_keys.RUN_ID]),
    }
    if operation.action == recoveryops.REPAIR_GRUB:
        arguments["preimage"] = recoveryops.preimage(before)
    if operation.action == recoveryops.ARM_GDM:
        arguments["bad_digest"] = operation.image("b")
    operation.report["change"] = operation.ask(FIXTURE, arguments, private_mounts=True)


def body(operation: operating.Operation) -> str | None:
    operation.report["scope"] = recoveryops.SCOPE
    if operation.action == recoveryops.VERIFY_INSTALLED:
        return _installed(operation)
    before = operation.ask(INSPECT)
    operation.report["before"] = before
    status = bootcstatus.parse(before.get("bootc"))
    if operation.action in recoveryops.CANDIDATE_BOUND:
        bootcstatus.require_booted(status, operation.image("a"))
    if operation.action == recoveryops.NATIVE_MIGRATION:
        operation.report["migration"] = operation.ask(OPERATE, {"operation": "migrate"})
        operation.report["production_migration"] = recoveryops.MIGRATION_BLOCKED
    elif operation.action == recoveryops.REBOOT:
        return _reboot(operation, status)
    elif operation.action in recoveryops.MUTATIONS:
        _change(operation, before)
    elif operation.action == recoveryops.COLLECT:
        collected = operation.ask(OPERATE, {"operation": "collect"})
        operation.report["collected"] = collected
        operation.report["evaluation"] = gdmfallback.evaluate(
            gdmfallback.require_journal(collected), good=operation.image("a"),
            bad=operation.image("b"),
        )
    operation.report["after"] = operation.ask(INSPECT)
    return None


STAGE = operating.stage(recoveryops.NAME, body)

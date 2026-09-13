"""Inspect, inject or verify the rescue of the initramfs fault, through one guest unit.

An injection is bound to the inspection the operator reviewed: the plan digest goes to the
guest, which refuses a plan that no longer matches what it sees. A rescue check that finds A
bound to the fault is BLOCKED, and the report says why not to reboot.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.kernel import encoding, errors, refusals
from apex.verification import initramfsops, operating, verifykeys

FIXTURE = "fixture.initramfs"


def body(operation: operating.Operation) -> str | None:
    arguments: dict[str, encoding.JsonValue] = {
        "action": operation.action,
        "good": operation.image("a"),
        "bad": operation.image("b"),
    }
    if operation.action == initramfsops.INJECT:
        inspection = operation.context.facts[verifykeys.INSPECTION]
        if inspection is None:
            raise errors.Refusal(
                refusals.RefusalReason.INSPECTION_MISMATCH,
                subject="review an inspection result before injecting",
            )
        plan = initramfsops.require_inspection(
            inspection,
            fixture=operation.fixture,
            images=operation.images,
            process=operation.context.facts[verifykeys.MACHINE_PROCESS],
        )
        arguments["run_id"] = str(operation.context.facts[composition_keys.RUN_ID])
        arguments["plan_sha256"] = plan
        operation.report["inspection_sha256"] = plan
    guest = operation.ask(FIXTURE, arguments, private_mounts=True)
    operation.report["guest"] = guest
    if guest.get("status") == initramfsops.BLOCKED:
        operation.report["reason"] = guest.get("reason")
        return initramfsops.BLOCKED
    return None


STAGE = operating.stage(initramfsops.NAME, body, after=(verifykeys.INSPECTION,))

"""One A/B update operation on the disposable guest, judged as the older tool judged it.

The state is read before and after; the provisioning lays the fixture in and creates the
account's sentinel; a switch is judged by what bootc staged, or by the rejection the policy
must give; a rollback by where the guest was and where it points; and every operation ends
with the sentinel read back unchanged.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import encoding, safepaths
from apex.verification import bootcstatus, operating, updateops, verifykeys

STATE = "update.state"
PROVISION = "update.provision"
OPERATE = "update.operate"
SENTINEL = "update.sentinel"


def _provision(operation: operating.Operation, before: encoding.Document) -> None:
    installed_a = operation.action == updateops.PROVISION_A
    parent = operation.located.document.get("parent")
    expected = (
        operation.image("a") if installed_a
        else str(parent.get("digest")) if isinstance(parent, dict) else ""
    )
    bootcstatus.require_booted(before["bootc"], expected)
    ports = operation.context.ports
    archive = safepaths.SafePath.regular_file(
        operation.located.payloads.path,
        within=operation.context.facts[composition_keys.RUNTIME_ROOT],
    )
    if ports.digests.file(archive) != operation.located.report.archive:
        raise bootcstatus.unexpected("payload archive checksum mismatch")
    upload = safepaths.RemotePath(f"{defaults.UPDATE_UPLOAD_PREFIX}{operation.fixture}.tar")
    ports.guest.send(
        operation.context.facts[verifykeys.GUEST], local=archive, remote=upload,
        deadline=defaults.TRANSFER_DEADLINE,
    )
    operation.report["provisioned"] = operation.ask(PROVISION, {
        "fixture": operation.fixture, "archive": str(upload),
        "archive_sha256": operation.located.report.archive.hex,
        "public_key_sha256": operation.located.report.public_key.hex,
        "policy_sha256": operation.located.report.files[updateops.POLICY_FILE].hex,
        "installed_a": installed_a,
    })
    operation.report["sentinel_creation"] = operation.ask(
        SENTINEL, {"action": "create"}, privileged=False
    )


def _switch(operation: operating.Operation, before: encoding.Document) -> None:
    source = updateops.SOURCES[operation.action]
    if operation.action != updateops.SWITCH_A:
        bootcstatus.require_booted(before["bootc"], operation.image("a"))
    switched = operation.ask(OPERATE, {
        "operation": "switch",
        "source": updateops.source_directory(operation.fixture, operation.action),
    })
    after = operation.ask(STATE)
    operation.report["after"] = after["bootc"]
    if source in updateops.REJECTIONS:
        updateops.require_rejection(source, switched, before["bootc"], after["bootc"])
        return
    updateops.require_switched(switched, after["bootc"], operation.image(source))


def _rollback(operation: operating.Operation, before: encoding.Document) -> None:
    bootcstatus.require_booted(before["bootc"], operation.image("b"))
    updateops.require_rollback_target(before["bootc"], operation.image("a"))
    rolled = operation.ask(OPERATE, {"operation": "rollback"})
    if rolled.get("returncode") != 0:
        raise bootcstatus.unexpected("bootc rollback did not succeed")
    operation.report["after"] = operation.ask(STATE)["bootc"]


def body(operation: operating.Operation) -> str | None:
    before = operation.ask(STATE)
    for name in ("boot_id", "versions", "kernel_inputs"):
        operation.report[name] = before.get(name)
    operation.report["before"] = before["bootc"]
    if operation.action in updateops.PROVISIONS:
        _provision(operation, before)
    else:
        policy = operation.located.report.files[updateops.POLICY_FILE].hex
        if before.get("policy_sha256") != policy:
            raise bootcstatus.unexpected("the actual consumer policy differs from the fixture")
        if operation.action == updateops.ROLLBACK:
            _rollback(operation, before)
        else:
            _switch(operation, before)
    sentinel = operation.ask(SENTINEL, {"action": "verify"}, privileged=False)
    operation.report["sentinel_sha256"] = sentinel.get("sha256")
    updateops.require_sentinel(sentinel)
    return None


STAGE = operating.stage(updateops.NAME, body)

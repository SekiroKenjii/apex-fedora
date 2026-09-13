"""The account's own file that every update and rollback must leave untouched.

Created once in the account's home before the first operation, and read back after each,
as the account itself and never as root: user data surviving the operation is what the
older tool proved with the same file.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, deployments, guestguard, units
from apex.config import defaults
from apex.kernel import encoding, errors, hashing, identifiers, quantities, refusals, safepaths
from apex.provisioning.fixtures import update_fixture

CREATE = "create"
VERIFY = "verify"
ACTIONS = (CREATE, VERIFY)
TEXT = update_fixture.SENTINEL_TEXT
PRIVATE = quantities.FileMode(0o600)


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    action = arguments.get("action")
    if action not in ACTIONS:
        raise errors.Refusal(refusals.RefusalReason.REQUEST_MALFORMED, subject=f"action {action!r}")
    guestguard.require_session_user(ports)
    path = safepaths.SafePath(Path.home() / defaults.UPDATE_SENTINEL_NAME)
    if action == CREATE:
        if ports.files.exists(path):
            raise deployments.unexpected(f"{path}: the sentinel already exists")
        digest = ports.files.write_atomic(path, TEXT, mode=PRIVATE)
    else:
        digest = hashing.digest_bytes(
            ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)
        )
    return {"action": str(action), "path": str(path), "sha256": digest.hex}


units.declare(units.Unit(id=identifiers.ProbeId("update.sentinel"), run=run))

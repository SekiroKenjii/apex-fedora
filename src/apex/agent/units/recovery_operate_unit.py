"""The two recovery operations that are one program each: the migration and the collection.

The migration asks bootupd to refresh the static GRUB configuration, which the older tool
recorded does not refresh an existing one; the collection reads the boot list, the journal
of the units the fault touches, and every record the observer left under the test directory.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, guestguard, observing, units
from apex.kernel import commands, encoding, errors, identifiers, refusals, safepaths
from apex.ports import files
from apex.provisioning.fixtures import recovery_fixture

MIGRATE = "migrate"
COLLECT = "collect"
OPERATIONS = (MIGRATE, COLLECT)
MIGRATION = commands.Argv.of("bootupctl", "migrate-static-grub-config")
COLLECTION: Mapping[str, commands.Argv] = {
    "boots": commands.Argv.of("journalctl", "--list-boots", "--no-pager"),
    "journal": commands.Argv.of(
        "journalctl", "-u", "gdm", "-u", "greenboot-healthcheck",
        "-u", "greenboot-set-rollback-trigger", "--no-pager", "-o", "json",
    ),
}
RECORD_SUFFIX = ".json"


def records(ports: agentports.AgentPorts) -> encoding.Document:
    """Every record under the recovery test directory, by path, as the observer wrote it."""
    directory = safepaths.SafePath(Path(recovery_fixture.TEST_DIRECTORY))
    if not ports.files.exists(directory):
        return {}
    return {
        str(directory / entry.relative): observing.text(ports, directory / entry.relative)
        for entry in ports.files.list_tree(directory)
        if entry.kind is files.EntryKind.REGULAR and entry.relative.endswith(RECORD_SUFFIX)
    }


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    operation = arguments.get("operation")
    if operation not in OPERATIONS:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject=f"operation {operation!r}"
        )
    guestguard.require_installed(ports)
    if operation == MIGRATE:
        return {"operation": MIGRATE, "program": observing.program(ports, MIGRATION)}
    return {
        "operation": COLLECT,
        "programs": observing.programs(ports, COLLECTION),
        "records": records(ports),
    }


units.declare(units.Unit(id=identifiers.ProbeId("recovery.operate"), run=run))

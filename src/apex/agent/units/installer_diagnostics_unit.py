"""Export the installer guest's logs before a cancelled installation reboots it.

This is `guest/installer-diagnostics.py` without its transport: the same guards, the same
logs read only when they are regular files and bounded at the same size, the same programs
with the same bounds, and the same bundle. The framing under the host's token, which the
older script wrote itself to the serial port, is the agent's to do for every unit.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, guestguard, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, safepaths
from apex.ports import files

SCHEMA = 1
PREFLIGHT = "/run/apex/installer-preflight.json"
LOGS = ("anaconda.log", "storage.log", "program.log")
LOG_DIRECTORY = "/tmp"  # noqa: S108
COMMANDS: Mapping[str, commands.Argv] = {
    "selinux": commands.Argv.of("getenforce"),
    "units": commands.Argv.of(
        "systemctl", "show", "anaconda.service", "anaconda-pre.service",
        "-p", "ActiveState", "-p", "Result", "-p", "ExecMainStatus",
    ),
    "journal": commands.Argv.of(
        "journalctl", "-b", "-n", "1000", "--no-pager", "-o", "short-monotonic"
    ),
    "disks": commands.Argv.of(
        "lsblk", "--json", "--bytes", "-o", "NAME,SIZE,TYPE,RO,SERIAL,MOUNTPOINTS"
    ),
}


def read_log(ports: agentports.AgentPorts, path: safepaths.SafePath) -> encoding.Document:
    """A regular file's bytes up to the limit, encoded; anything else is an error, in place."""
    limit = defaults.LOG_LIMIT.value
    try:
        if ports.files.inspect(path).kind is not files.EntryKind.REGULAR:
            return {"error": "not a regular file"}
        data = ports.files.read_bytes(path, limit=limit + 1)
    except errors.PortFailure as failure:
        return {"error": failure.cause}
    kept = data[:limit]
    return {
        "data": base64.b64encode(kept).decode(),
        "sha256": hashlib.sha256(kept).hexdigest(),
        "truncated": len(data) > limit,
    }


def _program(ports: agentports.AgentPorts, argv: commands.Argv) -> encoding.Document:
    limit = defaults.LOG_LIMIT.value
    try:
        completed = ports.processes.run(
            argv, deadline=defaults.OBSERVATION_DEADLINE, limit=commands.OutputLimit(limit)
        )
    except errors.PortFailure as failure:
        return {"error": failure.cause}
    error_limit = defaults.LOG_ERROR_LIMIT
    return {
        "returncode": completed.exit_code,
        "stdout": completed.stdout.decode(errors="replace"),
        "stderr": completed.stderr[:error_limit].decode(errors="replace"),
        "truncated": completed.truncated or len(completed.stderr) > error_limit,
    }


def run(
    ports: agentports.AgentPorts,
    *,
    arguments: Mapping[str, encoding.JsonValue],  # noqa: ARG001
) -> encoding.Document:
    # The capture token is the frame's, chosen by the host; this unit takes no arguments.
    guestguard.require_installer(ports)
    observations: dict[str, encoding.JsonValue] = {
        "preflight": read_log(ports, safepaths.SafePath(Path(PREFLIGHT)))
    }
    for name, argv in COMMANDS.items():
        observations[name] = _program(ports, argv)
    marker = ports.files.read_bytes(
        safepaths.SafePath(Path(defaults.INSTALLER_MARKER)), limit=defaults.DOCUMENT_LIMIT.value
    )
    boot_id = ports.files.read_bytes(
        safepaths.SafePath(Path(defaults.BOOT_ID)), limit=defaults.DOCUMENT_LIMIT.value
    )
    return {
        "schema": SCHEMA,
        "payload": encoding.parse_document(marker),
        "boot_id": boot_id.decode(errors="replace").strip(),
        "logs": {
            name: read_log(ports, safepaths.SafePath(Path(LOG_DIRECTORY) / name)) for name in LOGS
        },
        "observations": observations,
    }


units.declare(units.Unit(id=identifiers.ProbeId("installer.diagnostics"), run=run))

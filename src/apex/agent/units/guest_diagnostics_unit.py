"""Collect read-only diagnostics into a file the operator chose, created exclusively.

This is `guest/diagnostics.py`: the same six programs and the codec dumps under
`/proc/asound`, written to a destination that must not exist yet, so an earlier capture is
never overwritten. The report is also returned, so the host holds the same bytes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, quantities, refusals, safepaths

STATUS = "OBSERVATION"
DESTINATION_ARGUMENT = "destination"
ASOUND = safepaths.SafePath(Path("/proc/asound"))
CARD = re.compile(r"card[0-9]+")
CODEC_PREFIX = "codec#"
COMMANDS: Mapping[str, commands.Argv] = {
    "kernel": commands.Argv.of("uname", "-r"),
    "packages": commands.Argv.of(
        "rpm", "-q", "kernel-core", "libfprint", "fprintd", "alsa-ucm", "pipewire", "wireplumber"
    ),
    "audio": commands.Argv.of("wpctl", "status"),
    "mixer": commands.Argv.of("amixer", "scontents"),
    "fprint_journal": commands.Argv.of(
        "journalctl", "-b", "-u", "fprintd", "--no-pager", "-n", "120"
    ),
    "sessions": commands.Argv.of("loginctl", "list-sessions", "--no-legend"),
}


def _destination(arguments: Mapping[str, encoding.JsonValue]) -> safepaths.SafePath:
    value = arguments.get(DESTINATION_ARGUMENT)
    if not isinstance(value, str) or not value.startswith("/") or ".." in Path(value).parts:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"{DESTINATION_ARGUMENT} must be an absolute path with no climb",
        )
    return safepaths.SafePath(Path(value))


def _program(ports: agentports.AgentPorts, argv: commands.Argv) -> encoding.Document:
    try:
        completed = ports.processes.run(
            argv, deadline=defaults.PROBE_DEADLINE, limit=commands.OutputLimit.default()
        )
    except errors.PortFailure as failure:
        return {"error": failure.cause}
    return {
        "returncode": completed.exit_code,
        "stdout": completed.stdout.decode(errors="replace"),
        "stderr": completed.stderr.decode(errors="replace"),
    }


def _codecs(ports: agentports.AgentPorts) -> encoding.Document:
    found: dict[str, encoding.JsonValue] = {}
    try:
        cards = ports.files.list_directory(ASOUND)
    except errors.PortFailure:
        return found
    for card in cards:
        if not CARD.fullmatch(card.relative):
            continue
        try:
            entries = ports.files.list_directory(ASOUND / card.relative)
        except errors.PortFailure:
            continue
        for entry in entries:
            if entry.relative.startswith(CODEC_PREFIX):
                path = ASOUND / card.relative / entry.relative
                found[str(path)] = ports.files.read_bytes(
                    path, limit=defaults.DOCUMENT_LIMIT.value
                ).decode(errors="replace")
    return found


def collect(ports: agentports.AgentPorts) -> encoding.Document:
    return {
        "timestamp": ports.clock.stamp().rendered,
        "status": STATUS,
        "commands": {name: _program(ports, argv) for name, argv in COMMANDS.items()},
        "codecs": _codecs(ports),
    }


def run(
    ports: agentports.AgentPorts,
    *,
    arguments: Mapping[str, encoding.JsonValue],
) -> encoding.Document:
    destination = _destination(arguments)
    try:
        ports.files.reserve(
            destination, size=quantities.ByteCount(0), mode=defaults.RECORD_MODE
        )
    except errors.PortFailure as failure:
        raise errors.Refusal(
            refusals.RefusalReason.PROBE_DESTINATION_TAKEN,
            subject=str(destination),
            remedy=f"an earlier capture is kept, not overwritten: {failure.cause}",
        ) from failure
    report = collect(ports)
    ports.files.patch(destination, offset=0, payload=encoding.canonical(report) + b"\n")
    return {**report, "written_to": str(destination)}


units.declare(units.Unit(id=identifiers.ProbeId("guest.diagnostics"), run=run))

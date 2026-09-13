"""Report the guest's state without declaring a visual or a hardware test passed.

Every observation is one program run through the process port with a bound on its output.
A program that is missing is recorded as such and never stops the others from being read.
"""

from __future__ import annotations

from collections.abc import Mapping

from apex.agent import agentports, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers

VISUAL_TEST = "NOT TESTED"
OBSERVATIONS: Mapping[str, commands.Argv] = {
    "bootc": commands.Argv.of("bootc", "status", "--format", "json"),
    "gdm": commands.Argv.of("systemctl", "is-active", "gdm"),
    "dbus": commands.Argv.of(
        "busctl",
        "--system",
        "call",
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "GetId",
    ),
    "root_mount": commands.Argv.of(
        "findmnt", "--noheadings", "--output", "TARGET,SOURCE,FSTYPE,OPTIONS", "/"
    ),
    "failed_units": commands.Argv.of("systemctl", "--failed", "--no-legend"),
    "sessions": commands.Argv.of("loginctl", "list-sessions", "--no-legend"),
    "selinux": commands.Argv.of("getenforce"),
    "kernel": commands.Argv.of("uname", "-r"),
}


def _observe(ports: agentports.AgentPorts, argv: commands.Argv) -> encoding.Document:
    try:
        completed = ports.processes.run(
            argv, deadline=defaults.PROBE_DEADLINE, limit=commands.OutputLimit.default()
        )
    except errors.PortFailure as failure:
        return {"returncode": None, "error": failure.cause}
    return {
        "returncode": completed.exit_code,
        "stdout": completed.stdout.decode(errors="replace").strip(),
        "stderr": completed.stderr.decode(errors="replace").strip(),
    }


def run(
    ports: agentports.AgentPorts,
    *,
    arguments: Mapping[str, encoding.JsonValue],  # noqa: ARG001
) -> encoding.Document:
    # This probe takes no arguments; the shape is the unit contract and every unit keeps it.
    return {
        "observations": {name: _observe(ports, argv) for name, argv in OBSERVATIONS.items()},
        "visual_test": VISUAL_TEST,
    }


units.declare(units.Unit(id=identifiers.ProbeId("guest.state"), run=run))

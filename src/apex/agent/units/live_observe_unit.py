"""Read the live guest without changing its protection or declaring acceptance.

The observations are the older `live-probe.py`'s, program for program and file for file. The
block devices come from one snapshot of sysfs rather than a walk per attribute, which is the
one place this unit reads differently from the script it replaces.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, blockdevices, guestguard, observing, units
from apex.kernel import commands, encoding, identifiers, safepaths

NOT_TESTED = "NOT TESTED"
SCOPE = "Read-only Apex live VM observations"
COMMANDS: Mapping[str, commands.Argv] = {
    "mounts": commands.Argv.of(
        "findmnt", "--json", "--output", "TARGET,SOURCE,FSTYPE,OPTIONS,MAJ:MIN"
    ),
    "swap": commands.Argv.of(
        "swapon", "--show=NAME,TYPE,SIZE,USED,PRIO", "--raw", "--noheadings", "--bytes"
    ),
    "selinux": commands.Argv.of("getenforce"),
    "kernel": commands.Argv.of("uname", "-r"),
    "critical-units": commands.Argv.of(
        "systemctl", "show", "gdm.service", "apex-live-protection.service",
        "livesys.service", "-p", "Id", "-p", "ActiveState", "-p", "SubState",
        "-p", "Result", "-p", "ExecMainStatus",
    ),
    "masked-units": commands.Argv.of(
        "systemctl", "show", "udisks2.service", "swap.target",
        "bootc-fetch-apply-updates.service", "greenboot-healthcheck.service",
        "bootloader-update.service",
        "-p", "Id", "-p", "UnitFileState", "-p", "ActiveState",
    ),
    "flatpak-helper": commands.Argv.of(
        "systemctl", "show", "flatpak-system-helper.service",
        "-p", "ActiveState", "-p", "Result", "-p", "ExecMainStatus",
    ),
    "failed-units": commands.Argv.of("systemctl", "--failed", "--no-legend", "--no-pager"),
    "sessions": commands.Argv.of("loginctl", "list-sessions", "--no-legend"),
    "protection-journal": commands.Argv.of(
        "journalctl", "-b", "--no-pager", "-n", "300",
        "-u", "apex-live-protection.service", "-u", "livesys.service",
    ),
    "warnings": commands.Argv.of("journalctl", "-b", "--no-pager", "-p", "warning", "-n", "300"),
    "installer-package": commands.Argv.of("rpm", "-q", "anaconda-core"),
}
FILES = (
    "/proc/cmdline",
    "/proc/swaps",
    "/run/apex-disks-protected",
    "/run/apex-protection-failed",
    "/usr/libexec/apex/live-disk-guard.sh",
)
EXECUTABLES = (
    "/usr/libexec/flatpak-system-helper",
    "/run/rootfsbase/usr/libexec/flatpak-system-helper",
)


def run(
    ports: agentports.AgentPorts,
    *,
    arguments: Mapping[str, encoding.JsonValue],  # noqa: ARG001
) -> encoding.Document:
    # This probe takes no arguments; the shape is the unit contract and every unit keeps it.
    guestguard.require_live(ports)
    return {
        "scope": SCOPE,
        "live_acceptance": NOT_TESTED,
        "write_denial_test": NOT_TESTED,
        "commands": observing.programs(ports, COMMANDS),
        "files": observing.texts(ports, FILES),
        "executable_metadata": {
            name: observing.metadata(ports, safepaths.SafePath(Path(name)))
            for name in EXECUTABLES
        },
        "block_devices": blockdevices.Snapshot.take(ports.files).document(),
    }


units.declare(units.Unit(id=identifiers.ProbeId("live.observe"), run=run))

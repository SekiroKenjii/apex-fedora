"""Read storage mappings and session state in a disposable Ventoy boot.

The programs and files are the older `ventoy-probe.py`'s. The block topology comes from the
shared sysfs snapshot; a partition reports no slaves, as the older script took care to keep.
"""

from __future__ import annotations

from collections.abc import Mapping

from apex.agent import agentports, blockdevices, guestguard, observing, units
from apex.kernel import commands, encoding, identifiers

SCOPE = "Read-only virtual Ventoy observations; no automatic acceptance"
COMMANDS: Mapping[str, commands.Argv] = {
    "disks": commands.Argv.of(
        "lsblk",
        "--json",
        "-o",
        "NAME,TYPE,MAJ:MIN,SIZE,FSTYPE,LABEL,RO,MOUNTPOINTS,TRAN,SERIAL,PKNAME",
    ),
    "mounts": commands.Argv.of("findmnt", "--json", "-o", "TARGET,SOURCE,FSTYPE,OPTIONS,MAJ:MIN"),
    "dm-table": commands.Argv.of("dmsetup", "table"),
    "dm-info": commands.Argv.of("dmsetup", "info", "-c"),
    "sessions": commands.Argv.of("loginctl", "list-sessions", "--no-legend"),
    "failed-units": commands.Argv.of("systemctl", "--failed", "--no-pager", "--no-legend"),
    "gdm": commands.Argv.of(
        "systemctl", "show", "gdm.service", "-p", "ActiveState", "-p", "Result"
    ),
    "firmware-entries": commands.Argv.of("efibootmgr", "-v"),
    "selinux": commands.Argv.of("getenforce"),
}
FILES = ("/proc/cmdline", "/proc/swaps", "/etc/os-release")


def _topology(snapshot: blockdevices.Snapshot) -> encoding.Document:
    return {
        device.name: {
            "path": device.sysfs_path,
            "ro": "1" if device.read_only else "0",
            "dev": device.number.rendered,
            "slaves": None if device.slaves is None else list(device.slaves),
        }
        for device in snapshot.devices
    }


def run(
    ports: agentports.AgentPorts,
    *,
    arguments: Mapping[str, encoding.JsonValue],  # noqa: ARG001
) -> encoding.Document:
    # This probe takes no arguments; the shape is the unit contract and every unit keeps it.
    guestguard.require_virtual_root(ports)
    return {
        "scope": SCOPE,
        "commands": observing.programs(ports, COMMANDS),
        "blocks": _topology(blockdevices.Snapshot.take(ports.files)),
        "files": observing.texts(ports, FILES),
    }


units.declare(units.Unit(id=identifiers.ProbeId("ventoy.observe"), run=run))

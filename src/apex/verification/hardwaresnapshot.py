"""Read-only observations of the host's audio and fingerprint state, through the ports.

The same files, the same programs and the same report as the older `hardware-snapshot`,
read through the file port and run through the process port with the same bounds, and
written once under a fresh directory beside the store. Nothing here enrols a finger,
claims a sensor, plays audio, writes a codec register or restarts a service; the report
says so in its own scope line, and the acceptance fields stay NOT TESTED because a
snapshot is not a test.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from apex.config import defaults
from apex.kernel import commands, encoding, errors, safepaths
from apex.ports import portset

SCOPE = "Read-only observations of the current system, not hardware acceptance"
UNKNOWN = "UNKNOWN"
NOT_TESTED = "NOT TESTED"
READ = "READ"
UNAVAILABLE = "UNAVAILABLE"
FIXED_PATHS = (
    "/etc/os-release", "/proc/sys/kernel/random/boot_id", "/proc/uptime", "/proc/cmdline",
    "/proc/asound/cards", "/proc/asound/pcm", "/sys/class/dmi/id/sys_vendor",
    "/sys/class/dmi/id/product_name", "/sys/class/dmi/id/board_name",
    "/sys/module/snd_hda_intel/parameters/model",
)
ASOUND = Path("/proc/asound")
SOUND_CLASS = Path("/sys/class/sound")
USB_DEVICES = Path("/sys/bus/usb/devices")
CARD = re.compile(r"card[0-9]+")
CODEC = re.compile(r"hwC[0-9]+D[0-9]+")
CODEC_FILES = (
    "init_pin_configs", "driver_pin_configs", "user_pin_configs", "init_verbs", "hints",
    "modelname", "subsystem_id", "vendor_id", "power/runtime_status",
)
FINGERPRINT_VENDOR = "04f3"
FINGERPRINT_PRODUCT = "0c6e"
COMMANDS: Mapping[str, tuple[str, ...]] = {
    "kernel": ("uname", "-r"),
    "pipewire": ("wpctl", "status"),
    "fingerprint-unit": (
        "systemctl", "show", "fprintd.service", "-p", "ActiveState", "-p", "MainPID",
        "-p", "ExecMainStartTimestampMonotonic", "-p", "NRestarts",
    ),
    "fingerprint-owner": (
        "busctl", "--system", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
        "org.freedesktop.DBus", "GetNameOwner", "s", "net.reactivated.Fprint",
    ),
    "fingerprint-journal": (
        "journalctl", "-b", "-u", "fprintd.service", "-n", "400", "-o", "short-monotonic",
        "--no-pager",
    ),
    "audio-kernel-journal": (
        "journalctl", "-b", "-k", "-g", "snd_hda|hdaudio|ALC294|audio", "-n", "300", "-o",
        "short-monotonic", "--no-pager",
    ),
    "audio-routing": ("pactl", "--format=json", "list", "sinks"),
}
RPM_PACKAGES = ("kernel-core", "libfprint", "fprintd", "pipewire", "wireplumber", "alsa-ucm")
DEB_PACKAGES = ("libfprint-2-2", "fprintd", "pipewire", "wireplumber", "alsa-ucm-conf")


def read(ports: portset.HostPorts, path: Path) -> encoding.Document:
    limit = defaults.SNAPSHOT_READ_LIMIT.value
    try:
        data = ports.files.read_bytes(safepaths.SafePath(path), limit=limit + 1)
    except errors.PortFailure as failure:
        return {"status": UNAVAILABLE, "error": failure.cause}
    return {
        "status": READ,
        "text": data[:limit].decode(errors="replace"),
        "truncated": len(data) > limit,
    }


def command(ports: portset.HostPorts, argv: Sequence[str]) -> encoding.Document:
    listed = list(argv)
    if ports.processes.locate(argv[0]) is None:
        return {"status": UNAVAILABLE, "reason": "Tool is not installed", "argv": listed}
    limit = defaults.SNAPSHOT_READ_LIMIT.value
    try:
        completed = ports.processes.run(
            commands.Argv.of(*argv),
            deadline=defaults.SNAPSHOT_COMMAND_DEADLINE,
            limit=commands.OutputLimit(limit + 1),
        )
    except errors.PortFailure as failure:
        return {"status": UNAVAILABLE, "reason": failure.cause, "argv": listed}
    return {
        "status": READ if completed.succeeded else UNAVAILABLE,
        "argv": listed,
        "returncode": completed.exit_code,
        "stdout": completed.stdout[:limit].decode(errors="replace"),
        "stderr": completed.stderr[:limit].decode(errors="replace"),
        "truncated": len(completed.stdout) > limit or len(completed.stderr) > limit,
    }


def _entries(ports: portset.HostPorts, directory: Path) -> tuple[str, ...]:
    try:
        listed = ports.files.list_directory(safepaths.SafePath(directory))
    except errors.PortFailure:
        return ()
    return tuple(entry.relative for entry in listed)


def _cards(ports: portset.HostPorts) -> tuple[str, ...]:
    return tuple(name for name in _entries(ports, ASOUND) if CARD.fullmatch(name))


def paths(ports: portset.HostPorts) -> tuple[Path, ...]:
    """The fixed files, every card's codec dumps, and every codec's sysfs configuration."""
    found = [Path(item) for item in FIXED_PATHS]
    for card in _cards(ports):
        found.extend(
            ASOUND / card / name for name in _entries(ports, ASOUND / card)
            if name.startswith("codec#")
        )
    for codec in _entries(ports, SOUND_CLASS):
        if CODEC.fullmatch(codec):
            found.extend(SOUND_CLASS / codec / name for name in CODEC_FILES)
    return tuple(found)


def programs(ports: portset.HostPorts) -> dict[str, tuple[str, ...]]:
    """The fixed programs, the package query the host has, and one mixer dump per card."""
    found = dict(COMMANDS)
    if ports.processes.locate("dpkg-query") is not None:
        found["packages"] = ("dpkg-query", "-W", *DEB_PACKAGES)
    elif ports.processes.locate("rpm") is not None:
        found["packages"] = ("rpm", "-q", *RPM_PACKAGES)
    for card in _cards(ports):
        found[f"{card}-mixer"] = ("amixer", "-c", card[len("card"):], "contents")
    return found


def usb_devices(ports: portset.HostPorts) -> list[encoding.JsonValue]:
    found: list[encoding.JsonValue] = []
    for name in _entries(ports, USB_DEVICES):
        device = USB_DEVICES / name
        vendor = read(ports, device / "idVendor")
        product = read(ports, device / "idProduct")
        if (
            str(vendor.get("text", "")).strip() == FINGERPRINT_VENDOR
            and str(product.get("text", "")).strip() == FINGERPRINT_PRODUCT
        ):
            found.append({
                "path": str(device),
                "id": f"{FINGERPRINT_VENDOR}:{FINGERPRINT_PRODUCT}",
                "product": read(ports, device / "product"),
                "runtime_status": read(ports, device / "power/runtime_status"),
            })
    return found


def observe(ports: portset.HostPorts) -> encoding.Document:
    return {
        "created_at": ports.clock.stamp().rendered,
        "scope": SCOPE,
        "cold_boot_provenance": UNKNOWN,
        "prior_workaround_state": UNKNOWN,
        "audio_acceptance": NOT_TESTED,
        "fingerprint_acceptance": NOT_TESTED,
        "files": {str(path): read(ports, path) for path in paths(ports)},
        "commands": {label: command(ports, argv) for label, argv in programs(ports).items()},
        "usb_devices": usb_devices(ports),
    }


def collect(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> safepaths.SafePath:
    """One observation written under a fresh directory, never over an earlier one."""
    token = ports.identities.token()
    target = root.child(
        f"{defaults.HARDWARE_OBSERVATIONS_DIRECTORY}/{token}/{defaults.OBSERVATIONS_NAME}"
    )
    ports.files.write_atomic(
        target, encoding.canonical(observe(ports)) + b"\n", mode=defaults.RECORD_MODE
    )
    return target

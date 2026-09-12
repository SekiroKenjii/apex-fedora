"""The two GTK programs the desktop probes show, carried verbatim and run in the user session.

`render-probe.py` draws three wide colour bars in a GTK4 window and `theme-probe.py` shows
native GTK3 or libadwaita controls; a screenshot on the host is what judges them, so their
bytes are the ones the recorded results were made with and they are not rewritten. Each is
placed where the older host installed it, with the mode it used, and started as a transient
user unit under Wayland the way the older host started it.
"""

from __future__ import annotations

import dataclasses
from importlib import resources
from pathlib import Path

from apex.kernel import commands, hashing, identifiers, quantities, safepaths
from apex.ports import files

SUFFIX = ".verbatim"
PACKAGE = "apex.assets.verbatim"
PRIVATE = quantities.FileMode(0o600)
BACKEND = "GDK_BACKEND=wayland"
PRESENTED = "window-presented"


@dataclasses.dataclass(frozen=True, slots=True)
class Program:
    asset: str
    installed: safepaths.SafePath

    def source(self) -> bytes:
        return resources.files(PACKAGE).joinpath(self.asset + SUFFIX).read_bytes()

    def digest(self) -> identifiers.Digest:
        return hashing.digest_bytes(self.source())

    def place(self, port: files.FileSystemPort) -> identifiers.Digest:
        """Write the program where the older host installed it, private to the user."""
        return port.write_atomic(self.installed, self.source(), mode=PRIVATE)


RENDER = Program(
    asset="render-probe.py", installed=safepaths.SafePath(Path("/var/tmp/apex-render-probe.py"))
)
THEME = Program(
    asset="theme-probe.py", installed=safepaths.SafePath(Path("/var/tmp/apex-theme-probe.py"))
)


def launch(program: Program, unit: str, *arguments: str) -> commands.Argv:
    """Start the program as a transient unit of the user's manager, collected when it ends."""
    return commands.Argv.of(
        "systemd-run", "--user", f"--unit={unit}", "--collect", f"--setenv={BACKEND}",
        "python3", program.installed, *arguments,
    )


def journal(unit: str) -> commands.Argv:
    return commands.Argv.of("journalctl", "--user", "-u", unit, "--no-pager")


def stop(unit: str) -> commands.Argv:
    return commands.Argv.of("systemctl", "--user", "stop", unit)

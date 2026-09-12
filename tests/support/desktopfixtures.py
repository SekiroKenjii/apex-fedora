"""A logged-in Wayland session as the desktop probes expect it, answered from one spec.

The spec says whether the Shell is on the user's bus, what starting a program returns and
what its journal shows over time; the fake process answers from it and a parity harness
reads the same spec, so both sides see one session.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from apex.adapters.fakes import (
    fake_archives,
    fake_blockdevices,
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_extents,
    fake_files,
    fake_ids,
    fake_process,
)
from apex.agent import agentports
from apex.config import defaults
from apex.kernel import quantities, safepaths

PUBLIC = quantities.FileMode(0o444)
SHELL_OWNER = (
    "busctl", "--user", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
    "org.freedesktop.DBus", "GetConnectionUnixProcessID", "s", "org.gnome.Shell",
)
WAYLAND = "GdkWaylandDisplay"
COMPOSITION = {"palette": "Shadcn-Graphite", "source": "tools/compose-shell-theme"}


def presented_line(unit: str, *, mode: str | None = None, display: str = WAYLAND) -> str:
    event: dict[str, Any] = {"event": "window-presented", "display_type": display}
    if mode is not None:
        event = {"mode": mode, **event}
    return f"Sep 13 10:00:03 apex python3[2201]: {json.dumps(event)}\n"


@dataclasses.dataclass(frozen=True, slots=True)
class SessionSpec:
    virtualiser: str = "kvm"
    shell_owned: bool = True
    launch_exit: int = 0
    journal_polls_until_presented: int = 2
    presents: bool = True
    display: str = WAYLAND
    gtk_theme: str = "'Adwaita-dark'"
    shell_theme: str = "'Shadcn-Graphite'"
    extensions: str = "user-theme@gnome-shell-extensions.gcampax.github.com\n"


class Session(fake_process.ScriptedProcess):
    """Answers the session's programs; the journal fills in after a few polls."""

    def __init__(self, spec: SessionSpec) -> None:
        super().__init__()
        self.spec = spec
        self.polls: dict[str, int] = {}

    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        self.expect(vector, self._answer(vector))
        return super().run(argv, **keywords)

    def _answer(self, vector: tuple[str, ...]) -> fake_process.Reply:
        spec = self.spec
        if vector == ("systemd-detect-virt", "--vm"):
            return fake_process.Reply(stdout=f"{spec.virtualiser}\n".encode())
        if vector == SHELL_OWNER:
            if spec.shell_owned:
                return fake_process.Reply(stdout=b"u 1687\n")
            return fake_process.Reply(exit_code=1, stderr=b"Failed to call method\n")
        if vector[:1] == ("systemd-run",):
            return fake_process.Reply(exit_code=spec.launch_exit)
        if vector[:1] == ("journalctl",):
            return self._journal(vector[vector.index("-u") + 1])
        if vector[:1] == ("gsettings",):
            value = spec.gtk_theme if "gtk-theme" in vector else spec.shell_theme
            return fake_process.Reply(stdout=f"{value}\n".encode())
        if vector[:1] == ("gnome-extensions",):
            return fake_process.Reply(stdout=spec.extensions.encode())
        return fake_process.Reply()

    def _journal(self, unit: str) -> fake_process.Reply:
        spec = self.spec
        self.polls[unit] = self.polls.get(unit, 0) + 1
        if spec.presents and self.polls[unit] >= spec.journal_polls_until_presented:
            mode = unit.removeprefix("apex-theme-") if "theme" in unit else None
            return fake_process.Reply(
                stdout=presented_line(unit, mode=mode, display=spec.display).encode()
            )
        return fake_process.Reply(stdout=b"-- No entries --\n")


def session(
    spec: SessionSpec,
) -> tuple[Session, fake_files.MemoryFiles, fake_clock.ManualClock, agentports.AgentPorts]:
    files = fake_files.MemoryFiles()
    files.write_atomic(
        safepaths.SafePath(Path(defaults.SHELL_THEME_SOURCE)), json.dumps(COMPOSITION).encode(),
        mode=PUBLIC,
    )
    process = Session(spec)
    clock = fake_clock.ManualClock()
    ports = agentports.AgentPorts(
        processes=process, files=files, clock=clock, containers=fake_containers.FakeRegistry(),
        digests=fake_digesting.CountingDigests(), archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(), extents=fake_extents.FakeExtents(),
        blocks=fake_blockdevices.FakeBlockDevices(),
    )
    return process, files, clock, ports

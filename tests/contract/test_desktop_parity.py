"""The desktop units run the commands the older host ran over ssh, in the older order.

The older host's methods run with their shell patched to record each command and answer it
from the same spec the units' fake session answers from; their keyboard and screenshots are
stood in for, since those are the host's and belong to the stages. The units run on the
fake session. Once the install through stdin is read as the file write it became, and the
journal polls are collapsed, the commands must agree.
"""

from __future__ import annotations

import dataclasses
import json
import shlex
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from desktopfixtures import COMPOSITION, SessionSpec, presented_line, session

from apex.adapters.fakes import fake_files
from apex.agent import desktopprograms, guestguard
from apex.agent.units import (
    desktop_render_unit,
    desktop_theme_adwaita_unit,
    desktop_theme_gtk3_unit,
    desktop_theme_settings_unit,
)
from apex.config import defaults
from apex.kernel import quantities, safepaths
from apexlib import guesttest

DIGEST = "sha256:" + "a" * 64
GUARD = {"systemd-detect-virt", "busctl"}
LOGIN = {"loginctl"}
BARS = b"\xe6\x26\x26" * 100 + b"\x26\xbf\x40" * 100 + b"\x26\x4c\xe6" * 100
HEADER = b"P6\n300 100\n255\n"


class Recording(fake_files.MemoryFiles):
    def __init__(self) -> None:
        super().__init__()
        self.read: list[str] = []

    def read_bytes(self, path: safepaths.SafePath, *, limit: int) -> bytes:
        self.read.append(str(path))
        return super().read_bytes(path, limit=limit)


def older_answer(spec: SessionSpec, polls: dict[str, int], command: str) -> str:
    """What the older host's shell answered, from the same spec the fake session answers."""
    if command.startswith("journalctl"):
        unit = command.split("-u ", 1)[1].split()[0]
        polls[unit] = polls.get(unit, 0) + 1
        if polls[unit] >= spec.journal_polls_until_presented:
            mode = unit.removeprefix("apex-theme-") if "theme" in unit else None
            return presented_line(unit, mode=mode)
        return ""
    answers = {
        "loginctl show-session": "wayland\n",
        "gsettings get org.gnome.desktop.interface": f"{spec.gtk_theme}\n",
        "gsettings get org.gnome.shell.extensions.user-theme": f"{spec.shell_theme}\n",
        "gnome-extensions": spec.extensions,
        "cat ": json.dumps(COMPOSITION),
    }
    return next((value for prefix, value in answers.items() if command.startswith(prefix)), "")


def older_screenshot(path: Path) -> None:
    """The frames the older host's checks need: bars for the probe, a change for the Shell."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix != ".ppm":
        path.write_bytes(b"png")
    elif path.name == "shell-before.ppm":
        path.write_bytes(HEADER + b"\x00\x00\x00" * 300 * 100)
    elif path.name == "shell-surface.ppm":
        path.write_bytes(HEADER + b"\x40\x40\x40" * 300 * 100)
    else:
        path.write_bytes(HEADER + BARS * 100)


def older_guest(
    tmp_path: Path, spec: SessionSpec, monkeypatch: pytest.MonkeyPatch
) -> tuple[Any, list[tuple[str, str | None]]]:
    guest = guesttest.Guest.__new__(guesttest.Guest)
    guest.expected_digest = DIGEST
    guest.directory = tmp_path
    guest.user = "tester"
    recorded: list[tuple[str, str | None]] = []
    polls: dict[str, int] = {}

    def run(command: str, *, input: str | None = None, **_: Any) -> SimpleNamespace:  # noqa: A002
        recorded.append((command, input))
        return SimpleNamespace(returncode=0, stdout=older_answer(spec, polls, command), stderr="")

    monkeypatch.setattr(guest, "run", run)
    monkeypatch.setattr(guest, "keys", lambda *codes: None)
    monkeypatch.setattr(guest, "screenshot", older_screenshot)
    monkeypatch.setattr(guest, "prepare_desktop", lambda output: None)
    return guest, recorded


def collapsed(commands: list[str]) -> list[str]:
    kept: list[str] = []
    for command in commands:
        if kept and kept[-1] == command and command.startswith("journalctl"):
            continue
        kept.append(command)
    return kept


def older_side(recorded: list[tuple[str, str | None]], dropped: set[str]) -> list[str]:
    return collapsed([
        command for command, _ in recorded
        if command.split()[0] not in dropped and not command.startswith("install ")
    ])


def newer_side(calls: list[Any]) -> list[str]:
    return collapsed([
        shlex.join(list(call)) for call in calls if call.arguments[0] not in GUARD
    ])


@pytest.fixture(autouse=True)
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guesttest.time, "sleep", lambda _: None)
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 1000)


def test_the_render_probe_is_installed_started_and_read_as_the_older_host_did(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = SessionSpec(journal_polls_until_presented=1)
    guest, recorded = older_guest(tmp_path, spec, monkeypatch)
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"password": "Abc-123"}))
    guest.password_file = credentials
    seats = iter([None, "c1", "c2"])

    def seat_session(account: str | None = None, *, session_class: str | None = None) -> str | None:
        return next(seats)

    monkeypatch.setattr(guest, "seat_session", seat_session)
    output = tmp_path / "render"
    output.mkdir()

    guest.password_login_and_render(output)
    process, files, _, ports = session(spec)
    report = desktop_render_unit.run(ports, arguments={})

    assert newer_side(process.calls) == older_side(recorded, LOGIN)
    installs = [(command, given) for command, given in recorded if command.startswith("install ")]
    assert installs == [(
        "install -m 0600 /dev/stdin /var/tmp/apex-render-probe.py",
        desktopprograms.RENDER.source().decode(),
    )]
    installed = desktopprograms.RENDER.installed
    assert files.read_bytes(installed, limit=1 << 20) == desktopprograms.RENDER.source()
    assert files.mode_of(installed).value == 0o600
    assert report["display_type"] == "GdkWaylandDisplay"
    assert json.loads((output / "render.json").read_text())["digest"] == DIGEST


def test_the_theme_probes_and_settings_follow_the_older_theme_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = SessionSpec()
    guest, recorded = older_guest(tmp_path, spec, monkeypatch)
    output = tmp_path / "theme"
    output.mkdir()

    guest.theme_surfaces(output)
    process, _, _, ports = session(spec)
    files = Recording()
    files.write_atomic(
        safepaths.SafePath(Path(defaults.SHELL_THEME_SOURCE)), json.dumps(COMPOSITION).encode(),
        mode=quantities.FileMode(0o444),
    )
    ports = dataclasses.replace(ports, files=files)
    for unit in (desktop_theme_gtk3_unit, desktop_theme_adwaita_unit):
        unit.run(ports, arguments={})
        unit.run(ports, arguments={"action": "dismiss"})
    desktop_theme_settings_unit.run(ports, arguments={})

    older = older_side(recorded, set())
    composition = f"cat {defaults.SHELL_THEME_SOURCE}"
    assert older[-1] == composition
    assert newer_side(process.calls) == older[:-1]
    assert files.read == [defaults.SHELL_THEME_SOURCE]
    installs = [given for command, given in recorded if command.startswith("install ")]
    assert installs == [desktopprograms.THEME.source().decode()]
    written = json.loads((output / "theme-surfaces.json").read_text())
    assert written["shell_change"]["visual_identification"] == "NOT TESTED"

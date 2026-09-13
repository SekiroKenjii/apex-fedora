"""The desktop programs are their verbatim assets byte for byte, placed and started as before."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_files
from apex.agent import desktopprograms

REPOSITORY = Path(__file__).resolve().parents[3]
ASSETS = REPOSITORY / "src" / "apex" / "assets" / "verbatim"


@pytest.mark.parametrize("program", [desktopprograms.RENDER, desktopprograms.THEME])
def test_each_program_is_its_verbatim_asset_byte_for_byte(program: desktopprograms.Program) -> None:
    asset = (ASSETS / f"{program.asset}.verbatim").read_bytes()

    assert program.source() == asset
    assert program.digest().hex == hashlib.sha256(asset).hexdigest()


def test_a_program_is_placed_where_the_older_host_installed_it_and_private() -> None:
    files = fake_files.MemoryFiles()

    placed = desktopprograms.RENDER.place(files)

    installed = desktopprograms.RENDER.installed
    assert str(installed) == "/var/tmp/apex-render-probe.py"
    assert files.read_bytes(installed, limit=1 << 20) == desktopprograms.RENDER.source()
    assert files.mode_of(installed).value == 0o600
    assert placed == desktopprograms.RENDER.digest()


def test_the_program_starts_as_a_transient_user_unit_under_wayland() -> None:
    argv = desktopprograms.launch(desktopprograms.THEME, "apex-theme-gtk3", "gtk3")

    assert list(argv) == [
        "systemd-run",
        "--user",
        "--unit=apex-theme-gtk3",
        "--collect",
        "--setenv=GDK_BACKEND=wayland",
        "python3",
        "/var/tmp/apex-theme-probe.py",
        "gtk3",
    ]
    assert list(desktopprograms.journal("apex-theme-gtk3")) == [
        "journalctl",
        "--user",
        "-u",
        "apex-theme-gtk3",
        "--no-pager",
    ]
    assert list(desktopprograms.stop("apex-theme-gtk3")) == [
        "systemctl",
        "--user",
        "stop",
        "apex-theme-gtk3",
    ]

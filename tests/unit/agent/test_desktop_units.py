"""The desktop probes show a program as the session's user and read its journal, never a verdict."""

from __future__ import annotations

import json

import pytest
from desktopfixtures import COMPOSITION, SHELL_OWNER, WAYLAND, SessionSpec, session

from apex.agent import desktopprograms, guestguard
from apex.agent.units import (
    desktop_render_unit,
    desktop_theme_adwaita_unit,
    desktop_theme_gtk3_unit,
    desktop_theme_settings_unit,
)
from apex.kernel import errors, refusals, timing

VIRTUAL = ("systemd-detect-virt", "--vm")
JOURNAL = ("journalctl", "--user", "-u", "apex-render-probe", "--no-pager")


@pytest.fixture(autouse=True)
def as_the_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 1000)


def test_the_render_probe_is_placed_started_and_waited_for() -> None:
    process, files, clock, ports = session(SessionSpec())

    report = desktop_render_unit.run(ports, arguments={})

    assert report["presented"] is True
    assert report["display_type"] == WAYLAND
    assert report["rendering"] == "NOT TESTED"
    assert report["unit"] == "apex-render-probe"
    assert report["program_sha256"] == desktopprograms.RENDER.digest().hex
    installed = desktopprograms.RENDER.installed
    assert files.read_bytes(installed, limit=1 << 20) == desktopprograms.RENDER.source()
    assert files.mode_of(installed).value == 0o600
    assert [tuple(call) for call in process.calls] == [
        VIRTUAL,
        SHELL_OWNER,
        (
            "systemd-run",
            "--user",
            "--unit=apex-render-probe",
            "--collect",
            "--setenv=GDK_BACKEND=wayland",
            "python3",
            "/var/tmp/apex-render-probe.py",
        ),
        JOURNAL,
        JOURNAL,
    ]
    assert clock.slept == [timing.Elapsed(1)]


def test_a_window_that_never_appears_is_reported_not_raised() -> None:
    process, _, clock, ports = session(SessionSpec(presents=False))

    report = desktop_render_unit.run(ports, arguments={})

    assert report["presented"] is False
    assert report["display_type"] is None
    journal = report["journal"]
    assert isinstance(journal, dict) and journal["stdout"] == "-- No entries --\n"
    assert sum(span.seconds for span in clock.slept) >= 30
    assert process.polls["apex-render-probe"] >= 30


def test_a_program_that_fails_to_start_is_reported_without_polling() -> None:
    process, _, _, ports = session(SessionSpec(launch_exit=1))

    report = desktop_render_unit.run(ports, arguments={})

    assert report["presented"] is False
    launch = report["launch"]
    assert isinstance(launch, dict) and launch["returncode"] == 1
    assert report["journal"] == {}
    assert "journalctl" not in [call.arguments[0] for call in process.calls]


@pytest.mark.parametrize(
    "unit,mode", [(desktop_theme_gtk3_unit, "gtk3"), (desktop_theme_adwaita_unit, "adwaita")]
)
def test_a_theme_probe_presents_its_mode_and_stops_on_request(unit: object, mode: str) -> None:
    process, files, _, ports = session(SessionSpec())
    run = getattr(unit, "run")  # noqa: B009

    shown = run(ports, arguments={})
    dismissed = run(ports, arguments={"action": "dismiss"})

    assert shown["mode"] == mode and shown["unit"] == f"apex-theme-{mode}"
    assert shown["presented"] is True and shown["visual_review"] == "NOT TESTED"
    assert shown["program_sha256"] == desktopprograms.THEME.digest().hex
    assert files.mode_of(desktopprograms.THEME.installed).value == 0o600
    launch = shown["launch"]
    assert isinstance(launch, dict) and launch["argv"] == [
        "systemd-run",
        "--user",
        f"--unit=apex-theme-{mode}",
        "--collect",
        "--setenv=GDK_BACKEND=wayland",
        "python3",
        "/var/tmp/apex-theme-probe.py",
        mode,
    ]
    stop = dismissed["stop"]
    assert isinstance(stop, dict) and stop["argv"] == [
        "systemctl",
        "--user",
        "stop",
        f"apex-theme-{mode}",
    ]
    assert [tuple(call) for call in process.calls][-1] == (
        "systemctl",
        "--user",
        "stop",
        f"apex-theme-{mode}",
    )


def test_an_unknown_action_is_refused_before_any_program() -> None:
    process, _, _, ports = session(SessionSpec())

    with pytest.raises(errors.Refusal) as caught:
        desktop_theme_gtk3_unit.run(ports, arguments={"action": "restart"})

    assert caught.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert process.calls == []


def test_the_settings_probe_reads_themes_extensions_and_the_composition() -> None:
    _, _, _, ports = session(SessionSpec())

    report = desktop_theme_settings_unit.run(ports, arguments={})

    settings = report["settings"]
    assert isinstance(settings, dict)
    assert settings["gtk_theme"]["stdout"] == "'Adwaita-dark'\n"  # type: ignore[index]
    assert settings["shell_theme"]["stdout"] == "'Shadcn-Graphite'\n"  # type: ignore[index]
    assert settings["extensions"]["stdout"].startswith("user-theme@")  # type: ignore[index,union-attr]
    composition = report["composition"]
    assert isinstance(composition, dict)
    assert json.loads(str(composition["text"])) == COMPOSITION
    assert report["visual_review"] == "NOT TESTED"
    assert "status" not in report


@pytest.mark.parametrize(
    "spec,euid",
    [
        (SessionSpec(), 0),
        (SessionSpec(shell_owned=False), 1000),
        (SessionSpec(virtualiser="none"), 1000),
    ],
)
def test_outside_a_users_shell_session_in_a_guest_every_desktop_probe_refuses(
    spec: SessionSpec, euid: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: euid)
    process, _, _, ports = session(spec)

    with pytest.raises(errors.Refusal) as caught:
        desktop_render_unit.run(ports, arguments={})

    assert caught.value.reason is refusals.RefusalReason.PROBE_ENVIRONMENT_UNEXPECTED
    assert "systemd-run" not in [call.arguments[0] for call in process.calls]

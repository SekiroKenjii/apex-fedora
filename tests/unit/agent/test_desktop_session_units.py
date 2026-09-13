"""The login probes read the seat and the Shell's bus as the account, and never judge."""

from __future__ import annotations

import pytest
from desktopfixtures import (
    GREETER_ID,
    LIST_SESSIONS,
    OVERVIEW,
    SESSION_ID,
    SHELL_OWNER,
    STARTED_EVENT,
    SessionSpec,
    session,
)

from apex.agent import guestguard
from apex.agent.units import (
    desktop_greeter_unit,
    desktop_overview_unit,
    desktop_session_unit,
    desktop_shell_startup_unit,
)
from apex.kernel import errors, refusals

VIRTUAL = ("systemd-detect-virt", "--vm")
SHOW_GREETER = ("loginctl", "show-session", GREETER_ID, "-p", "Class", "-p", "Type")


@pytest.fixture(autouse=True)
def as_the_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 1000)


def test_the_greeter_is_reported_once_it_appears_on_the_seat() -> None:
    process, _, clock, ports = session(SessionSpec(greeter_after=3))

    report = desktop_greeter_unit.run(ports, arguments={})

    assert report["found"] is True
    assert report["session"] == {
        "id": GREETER_ID,
        "user": "gdm",
        "seat": "seat0",
        "class": "greeter",
        "type": "wayland",
    }
    assert report["sessions"] == [report["session"]]
    assert [tuple(call) for call in process.calls] == [
        VIRTUAL,
        LIST_SESSIONS,
        LIST_SESSIONS,
        LIST_SESSIONS,
        SHOW_GREETER,
    ]
    assert sum(span.seconds for span in clock.slept) == 2


def test_a_greeter_that_never_comes_is_reported_after_the_older_minute() -> None:
    process, _, clock, ports = session(SessionSpec(greeter_after=None))

    report = desktop_greeter_unit.run(ports, arguments={})

    assert report["found"] is False and report["session"] is None
    assert report["sessions"] == []
    assert sum(span.seconds for span in clock.slept) >= 60
    assert process.polls["list-sessions"] >= 60


def test_the_greeter_probe_takes_no_arguments() -> None:
    process, _, _, ports = session(SessionSpec())

    with pytest.raises(errors.Refusal) as caught:
        desktop_greeter_unit.run(ports, arguments={"wait": True})

    assert caught.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert process.calls == []


def test_the_account_is_reported_absent_from_the_seat_without_waiting() -> None:
    _, _, clock, ports = session(SessionSpec())

    report = desktop_session_unit.run(ports, arguments={"user": "apex-test", "wait": False})

    assert report["found"] is False and report["wayland"] is False
    assert report["session"] is None
    assert [item["class"] for item in report["sessions"]] == ["greeter"]  # type: ignore[index]
    assert clock.slept == []


def test_the_accounts_wayland_session_is_waited_for() -> None:
    _, _, clock, ports = session(SessionSpec(login_after=2))

    report = desktop_session_unit.run(ports, arguments={"user": "apex-test", "wait": True})

    assert report["found"] is True and report["wayland"] is True and report["waited"] is True
    assert report["session"] == {
        "id": SESSION_ID,
        "user": "apex-test",
        "seat": "seat0",
        "class": "user",
        "type": "wayland",
    }
    assert sum(span.seconds for span in clock.slept) == 1


def test_a_session_that_is_not_wayland_is_not_the_one_waited_for() -> None:
    _, _, clock, ports = session(SessionSpec(login_after=1, login_type="x11"))

    report = desktop_session_unit.run(ports, arguments={"user": "apex-test", "wait": True})

    assert report["found"] is False and report["wayland"] is False
    assert [item["type"] for item in report["sessions"]] == ["wayland", "x11"]  # type: ignore[index]
    assert sum(span.seconds for span in clock.slept) >= 90


@pytest.mark.parametrize("arguments", [{}, {"user": "Root!"}, {"user": "apex-test", "wait": "yes"}])
def test_a_session_request_without_a_plain_account_is_refused(arguments: dict[str, object]) -> None:
    process, _, _, ports = session(SessionSpec())

    with pytest.raises(errors.Refusal) as caught:
        desktop_session_unit.run(ports, arguments=arguments)  # type: ignore[arg-type]

    assert caught.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert process.calls == []


def test_the_shell_startup_event_is_reported_as_the_journal_wrote_it() -> None:
    process, _, clock, ports = session(SessionSpec(startup_after=2))

    report = desktop_shell_startup_unit.run(ports, arguments={})

    assert report["found"] is True and report["pid"] == 1687
    assert report["event"] == STARTED_EVENT
    journal = desktop_shell_startup_unit.journal_query(1687)
    assert [tuple(call) for call in process.calls] == [
        VIRTUAL,
        SHELL_OWNER,
        tuple(journal),
        SHELL_OWNER,
        tuple(journal),
    ]
    assert sum(span.seconds for span in clock.slept) == 1


def test_a_shell_that_is_never_on_the_bus_is_reported_without_a_journal_query() -> None:
    process, _, clock, ports = session(SessionSpec(shell_owned=False))

    report = desktop_shell_startup_unit.run(ports, arguments={})

    assert report["found"] is False and report["pid"] is None and report["event"] is None
    assert "journalctl" not in [call.arguments[0] for call in process.calls]
    assert sum(span.seconds for span in clock.slept) >= 90


def test_the_overview_is_read_until_it_shows_the_expected_state() -> None:
    process, _, clock, ports = session(SessionSpec(overview_flips_after=2))

    report = desktop_overview_unit.run(ports, arguments={"expected": True})

    assert report["reached"] is True and report["polls"] == 2
    assert [tuple(call) for call in process.calls] == [VIRTUAL, SHELL_OWNER, OVERVIEW, OVERVIEW]
    assert sum(span.seconds for span in clock.slept) == 0.5


def test_an_overview_that_never_follows_is_reported_after_fifteen_seconds() -> None:
    _, _, clock, ports = session(SessionSpec(overview_active=False))

    report = desktop_overview_unit.run(ports, arguments={"expected": True})

    assert report["reached"] is False
    assert report["reply"]["stdout"] == "b false\n"  # type: ignore[index]
    assert sum(span.seconds for span in clock.slept) >= 15


def test_an_overview_request_without_an_expectation_is_refused() -> None:
    process, _, _, ports = session(SessionSpec())

    with pytest.raises(errors.Refusal) as caught:
        desktop_overview_unit.run(ports, arguments={"expected": "open"})

    assert caught.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert process.calls == []


@pytest.mark.parametrize(
    "unit,arguments",
    [
        (desktop_greeter_unit, {}),
        (desktop_session_unit, {"user": "apex-test", "wait": False}),
        (desktop_shell_startup_unit, {}),
        (desktop_overview_unit, {"expected": False}),
    ],
)
def test_as_root_every_login_probe_refuses(
    unit: object, arguments: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)
    process, _, _, ports = session(SessionSpec())
    run = getattr(unit, "run")  # noqa: B009

    with pytest.raises(errors.Refusal) as caught:
        run(ports, arguments=arguments)

    assert caught.value.reason is refusals.RefusalReason.PROBE_ENVIRONMENT_UNEXPECTED
    assert process.calls == []


def test_the_login_probes_do_not_need_the_shell_but_the_overview_does() -> None:
    _, _, _, ports = session(SessionSpec(shell_owned=False))

    assert desktop_greeter_unit.run(ports, arguments={})["found"] is True

    with pytest.raises(errors.Refusal):
        desktop_overview_unit.run(ports, arguments={"expected": False})

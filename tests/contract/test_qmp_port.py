"""One monitor conversation: greeting, capabilities, replies matched by identifier."""

from __future__ import annotations

from typing import Protocol

import pytest

from apex.config import defaults
from apex.kernel import errors, safepaths
from apex.ports import qmp


class Monitor(Protocol):
    port: qmp.QmpPort
    socket: safepaths.SafePath


def test_a_command_answers_with_its_return_value(monitors: Monitor) -> None:
    with monitors.port.connect(monitors.socket, deadline=defaults.QMP_DEADLINE) as session:
        assert session.execute(qmp.QmpCommand("query-status")) == {"status": "running"}


def test_an_event_before_the_reply_is_skipped(monitors: Monitor) -> None:
    with monitors.port.connect(monitors.socket, deadline=defaults.QMP_DEADLINE) as session:
        first = session.execute(qmp.QmpCommand("query-status"))
        second = session.execute(qmp.QmpCommand("system_powerdown"))

    assert first == {"status": "running"}
    assert second == {}


def test_a_command_the_machine_rejects_is_a_port_failure(monitors: Monitor) -> None:
    with (
        monitors.port.connect(monitors.socket, deadline=defaults.QMP_DEADLINE) as session,
        pytest.raises(errors.PortFailure) as raised,
    ):
        session.execute(qmp.QmpCommand("apex-no-such-command"))

    assert "apex-no-such-command" in str(raised.value)


def test_a_machine_that_closes_its_monitor_is_a_port_failure(monitors: Monitor) -> None:
    with (
        monitors.port.connect(monitors.socket, deadline=defaults.QMP_DEADLINE) as session,
        pytest.raises(errors.PortFailure),
    ):
        session.execute(qmp.QmpCommand("quit"))


def test_a_monitor_that_is_not_there_is_a_port_failure(monitors: Monitor) -> None:
    absent = monitors.socket.path.with_name("absent.sock")
    port = monitors.port
    if hasattr(port, "reply"):
        port = type(port)(reachable=False)  # type: ignore[call-arg]

    with pytest.raises(errors.PortFailure):
        port.connect(type(monitors.socket)(absent), deadline=defaults.QMP_DEADLINE).__enter__()

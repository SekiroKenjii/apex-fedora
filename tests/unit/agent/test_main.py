"""The agent program: a handshake, a request in, a reply out, and nothing else on stdout."""

from __future__ import annotations

import io
import json

import pytest

from apex.adapters.fakes import (
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_files,
    fake_process,
)
from apex.agent import agentports, main
from apex.kernel import errors, identifiers, refusals
from apex.model import agentwire, serialframe

TOKEN = "c" * 32


def request(unit: str = "guest.state") -> bytes:
    return json.dumps(
        {
            "protocol": agentwire.PROTOCOL_VERSION,
            "host_version": "0.2.0",
            "unit": unit,
            "arguments": {},
            "agent_digest": "a" * 64,
        }
    ).encode()


def bundle() -> agentports.AgentPorts:
    process = fake_process.ScriptedProcess()
    for argv in (
        ("bootc", "status", "--format", "json"),
        ("systemctl", "is-active", "gdm"),
        ("busctl", "--system", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
         "org.freedesktop.DBus", "GetId"),
        ("findmnt", "--noheadings", "--output", "TARGET,SOURCE,FSTYPE,OPTIONS", "/"),
        ("systemctl", "--failed", "--no-legend"),
        ("loginctl", "list-sessions", "--no-legend"),
        ("getenforce",),
        ("uname", "-r"),
    ):
        process.expect(argv, fake_process.Reply(stdout=b"ok\n"))
    return agentports.AgentPorts(
        processes=process, files=fake_files.MemoryFiles(), clock=fake_clock.ManualClock(),
        containers=fake_containers.FakeRegistry(),
        digests=fake_digesting.CountingDigests(),
    )


def test_the_handshake_is_one_json_document(capsys: pytest.CaptureFixture[str]) -> None:
    assert main.main(["handshake"]) == 0

    document = json.loads(capsys.readouterr().out)
    assert document["protocol"] == agentwire.PROTOCOL_VERSION
    assert document["agent_version"]


def test_a_request_is_answered_with_a_reply_for_its_unit() -> None:
    reply = main.dispatch(agentwire.AgentRequest.parse(request()), ports=bundle())

    assert str(reply.unit) == "guest.state"
    assert reply.observations["visual_test"] == "NOT TESTED"


def test_an_unknown_unit_is_refused() -> None:
    with pytest.raises(errors.Refusal) as raised:
        main.dispatch(agentwire.AgentRequest.parse(request("guest.nothing")), ports=bundle())

    assert raised.value.reason is refusals.RefusalReason.UNIT_UNKNOWN


def test_a_reply_can_be_written_as_frames(capsys: pytest.CaptureFixture[str]) -> None:
    reply = main.dispatch(agentwire.AgentRequest.parse(request()), ports=bundle())

    captured = io.StringIO()
    main.emit(reply, framed_with=identifiers.Token(TOKEN), stream=captured)

    lines = [line.encode() for line in captured.getvalue().splitlines() if line]
    payload = serialframe.decode_lines(lines, token=identifiers.Token(TOKEN))
    assert json.loads(payload) == reply.document()


def test_a_malformed_request_on_stdin_exits_as_a_refusal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"not a request")))

    assert main.main(["run"]) == errors.Refusal.exit_code
    assert capsys.readouterr().out == ""

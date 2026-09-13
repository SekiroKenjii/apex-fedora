"""The fingerprint trace keeps ownership events and drops names, arguments and error bodies."""

from __future__ import annotations

import contextlib
import dataclasses
import json
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_clock, fake_files, fake_process
from apex.config import defaults
from apex.kernel import safepaths
from apex.ports import portset
from apex.verification import fingerprinttrace

DEVICE = "/net/reactivated/Fprint/Device/0"
SERVICE = fingerprinttrace.SERVICE
INTERFACE = fingerprinttrace.INTERFACE
IN_USE = fingerprinttrace.ALREADY_IN_USE


def call(
    method: str = "Claim", client: str = ":1.2", serial: int = 2, destination: str = SERVICE
) -> dict[str, object]:
    return {
        "type": "method_call", "cookie": serial, "timestamp-realtime": 100, "sender": client,
        "destination": destination, "path": DEVICE, "interface": INTERFACE, "member": method,
        "payload": {"type": "s", "data": ["PRIVATE USERNAME"]},
    }


def reply(client: str = ":1.2", serial: int = 2, error: str | None = None) -> dict[str, object]:
    return {
        "type": "error" if error else "method_return", "reply_cookie": serial,
        "timestamp-realtime": 101, "sender": ":1.10", "destination": client,
        "error_name": error, "payload": {"type": "s", "data": ["PRIVATE ERROR BODY"]},
    }


def disconnect(client: str = ":1.2") -> dict[str, object]:
    return {
        "type": "signal", "timestamp-realtime": 102, "sender": "org.freedesktop.DBus",
        "interface": "org.freedesktop.DBus", "member": "NameOwnerChanged",
        "payload": {"type": "sss", "data": [client, client, ""]},
    }


def status() -> dict[str, object]:
    return {
        "type": "signal", "timestamp-realtime": 103, "sender": ":1.10", "path": DEVICE,
        "interface": INTERFACE, "member": "EnrollStatus",
        "payload": {"type": "sb", "data": ["enroll-disconnected", True]},
    }


def trace() -> fingerprinttrace.Trace:
    return fingerprinttrace.Trace(fake_clock.ManualClock())


def fed(*messages: dict[str, object]) -> fingerprinttrace.Trace:
    held = trace()
    for message in messages:
        held.feed(message)
    return held


def test_an_error_status_does_not_release_the_claim() -> None:
    held = fed(call(), reply(), status())

    assert held.owners[DEVICE] == ":1.2"
    assert held.summary()["fingerprint_acceptance"] == "NOT TESTED"
    assert held.summary()["successful_releases"] == 0


def test_a_second_client_is_denied_until_a_release_is_observed() -> None:
    held = fed(
        call(), reply(), call(client=":1.3"), reply(client=":1.3", error=IN_USE),
        call("Release", serial=3), reply(serial=3), call(client=":1.3", serial=4),
        reply(client=":1.3", serial=4),
    )

    assert held.owners[DEVICE] == ":1.3"
    assert held.summary()["claim_denials"] == held.summary()["successful_releases"] == 1
    denial = next(event for event in held.events if event.get("outcome") == "ERROR")
    assert denial["last_observed_owner"] == ":1.2" and denial["caller_was_last_owner"] is False


def test_a_reclaim_by_the_same_client_is_told_apart_from_another_process() -> None:
    held = fed(call(), reply(), call(serial=3), reply(serial=3, error=IN_USE))

    assert held.events[-1]["caller_was_last_owner"] is True


def test_a_disappearance_needs_a_later_success_to_confirm_reacquisition() -> None:
    held = fed(call(), reply(), disconnect())

    assert held.owners[DEVICE] == ":1.2"
    assert held.summary()["claims_after_disconnect"] == 0
    held.feed(call(client=":1.3"))
    held.feed(reply(client=":1.3"))
    assert held.summary()["claims_after_disconnect"] == 1


def test_a_serial_is_scoped_to_its_client_and_the_reply_destination() -> None:
    held = fed(call(), call(client=":1.3"), reply(client=":1.3", error=IN_USE))

    assert (":1.2", 2) in held.pending and held.owners == {}
    held.feed(reply())
    assert held.owners[DEVICE] == ":1.2"


def test_an_unknown_initial_owner_and_an_incomplete_trace_are_explicit() -> None:
    held = fed(call(), reply(error=IN_USE))

    assert held.events[-1]["last_observed_owner"] == "UNKNOWN"
    assert held.events[-1]["caller_was_last_owner"] is None
    held.feed(call("EnrollStart", serial=3))
    assert held.summary()["capture_status"] == "INCOMPLETE"


def test_usernames_error_bodies_and_unrelated_messages_are_dropped() -> None:
    held = fed(
        call(), reply(error=IN_USE), call("DeleteEnrolledFingers"), disconnect(":1.99")
    )

    combined = json.dumps([held.events, held.summary()])
    assert "PRIVATE" not in combined and "DeleteEnrolledFingers" not in combined
    assert ":1.99" not in combined
    altered = status()
    altered["payload"] = {"type": "sb", "data": ["SENSITIVE-UNKNOWN-STATUS", True]}
    found = held.feed(altered)
    assert found is not None and found["status"] == "UNKNOWN"


def test_a_daemon_replacement_forgets_every_ownership() -> None:
    held = fed(call(), reply())
    changed = disconnect()
    changed["payload"] = {"type": "sss", "data": [SERVICE, ":1.10", ":1.20"]}

    held.feed(changed)

    assert held.owners == held.pending == {}


def test_a_reply_from_another_sender_than_the_called_owner_is_malformed() -> None:
    held = fed(call(destination=":1.30"))

    with pytest.raises(ValueError, match="reply sender"):
        held.feed(reply())


@pytest.mark.parametrize(
    "message",
    [None, [], "private", {"type": "method_call"}, {"type": "signal", "payload": ["private"]}],
)
def test_malformed_or_unrelated_input_is_never_an_event(message: object) -> None:
    held = trace()

    with contextlib.suppress(ValueError):
        held.feed(message)

    assert held.events == []


def test_an_oversized_line_is_refused_before_it_is_parsed() -> None:
    with pytest.raises(ValueError, match="limit"):
        fingerprinttrace.parse_line(b"x" * (defaults.TRACE_LINE_LIMIT.value + 1))


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def host(ports: portset.HostPorts) -> portset.HostPorts:
    filesystem = fake_files.MemoryFiles()
    for name, data in (
        (defaults.KERNEL_RELEASE, b"7.1.13-200\n"), (defaults.BOOT_ID, b"boot-1\n"),
    ):
        filesystem.write_atomic(safepaths.SafePath(Path(name)), data, mode=defaults.RECORD_MODE)
    return dataclasses.replace(ports, files=filesystem)


def test_a_capture_keeps_only_sanitised_events_under_a_private_directory(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = host(ports)
    stream = "\n".join(json.dumps(m) for m in (call(), reply(), status())).encode() + b"\n"

    captured = fingerprinttrace.capture(held, root, stream, lookup_clients=False)

    assert captured.observed
    assert captured.directory.path.parent == root.path / "fingerprint-observations"
    events = held.files.read_bytes(captured.directory / "events.jsonl", limit=1 << 20)
    summary = held.files.read_bytes(captured.directory / "summary.json", limit=1 << 20)
    assert b"PRIVATE" not in events and b"PRIVATE" not in summary
    assert len(events.splitlines()) == 3
    for name in ("events.jsonl", "summary.json"):
        assert held.files.mode_of(captured.directory / name) == defaults.RECORD_MODE
    assert captured.summary["kernel"] == "7.1.13-200"
    assert captured.summary["boot_id"] == "boot-1"
    assert captured.summary["event_count"] == 3


def test_a_raw_transcript_is_rejected_without_retaining_its_payload(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = host(ports)

    captured = fingerprinttrace.capture(
        held, root, b"PRIVATE MALFORMED PAYLOAD\n" * 25, lookup_clients=False
    )

    assert not captured.observed
    errors = captured.summary["errors"]
    assert isinstance(errors, list) and len(errors) <= defaults.TRACE_ERROR_LIMIT
    assert "PRIVATE" not in json.dumps(captured.summary)


def test_a_transcript_cut_mid_event_is_incomplete(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = host(ports)
    stream = json.dumps(call()).encode() + b"\n" + json.dumps(reply()).encode()[:-4]

    captured = fingerprinttrace.capture(held, root, stream, lookup_clients=False)

    errors = captured.summary["errors"]
    assert isinstance(errors, list)
    assert fingerprinttrace.PARTIAL in errors and fingerprinttrace.MALFORMED in errors


def test_a_client_s_process_is_named_by_its_program_and_never_its_arguments(
    ports: portset.HostPorts,
) -> None:
    processes = fake_process.ScriptedProcess({
        (*fingerprinttrace.PROCESS_QUERY, ":1.2"): fake_process.Reply(stdout=b"u 4242\n"),
        (*fingerprinttrace.PROCESS_QUERY, ":1.3"): fake_process.Reply(exit_code=1),
    })
    filesystem = fake_files.MemoryFiles()
    filesystem.write_atomic(
        safepaths.SafePath(Path("/usr/bin/gnome-control-center")), b"", mode=defaults.RECORD_MODE
    )
    filesystem.symlink(
        safepaths.SafePath(Path("/proc/4242/exe")),
        target=safepaths.SafePath(Path("/usr/bin/gnome-control-center")),
    )
    held = dataclasses.replace(ports, processes=processes, files=filesystem)

    assert fingerprinttrace.client_process(held, ":1.2") == {
        "status": "OBSERVED", "pid": 4242, "executable": "gnome-control-center",
    }
    assert fingerprinttrace.client_process(held, ":1.3") == {"status": "UNKNOWN"}
    assert fingerprinttrace.client_process(held, "org.gnome.Shell") == {"status": "UNKNOWN"}

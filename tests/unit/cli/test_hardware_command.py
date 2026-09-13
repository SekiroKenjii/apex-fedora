"""The hardware command: a snapshot kept under the root, a bus trace reduced from stdin, a
coefficient decoded on paper."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_files
from apex.cli import commandspecs
from apex.cli.commands import hardware_command
from apex.config import defaults, loader
from apex.kernel import errors, refusals, safepaths
from apex.ports import portset
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]
CALL = {
    "type": "method_call",
    "cookie": 2,
    "timestamp-realtime": 100,
    "sender": ":1.2",
    "destination": "net.reactivated.Fprint",
    "path": "/net/reactivated/Fprint/Device/0",
    "interface": "net.reactivated.Fprint.Device",
    "member": "Claim",
    "payload": {"type": "s", "data": ["PRIVATE"]},
}
REPLY = {
    "type": "method_return",
    "reply_cookie": 2,
    "timestamp-realtime": 101,
    "sender": ":1.10",
    "destination": ":1.2",
}


def request(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot | None, *arguments: str, stdin: str = ""
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=loader.load(host_file=None, environment={}),
            repository=safepaths.SourceRoot.adopt(REPOSITORY),
            root=root,
            environment={},
            bundle=lambda _root: ports,
        ),
        read_input=lambda: stdin,
    )


def host(ports: portset.HostPorts) -> portset.HostPorts:
    filesystem = fake_files.MemoryFiles()
    for name in (defaults.KERNEL_RELEASE, defaults.BOOT_ID):
        filesystem.write_atomic(safepaths.SafePath(Path(name)), b"x\n", mode=defaults.RECORD_MODE)
    return dataclasses.replace(ports, files=filesystem)


def test_a_coefficient_is_decoded_without_a_root_or_a_device(ports: portset.HostPorts) -> None:
    reply = hardware_command.run(request(ports, None, "decode-coefficient", "0x20", "0x500", "0x0"))

    assert reply.exit_code == 0
    assert reply.document == {
        "nid": "0x20",
        "hwdep_word": "0x20050000",
        "canonical_verb": "0x500",
        "effective_parameter": "0x0000",
        "parameter_changed_by_overlap": False,
        "device_access": False,
    }


def test_a_snapshot_lands_under_the_root_and_needs_one(
    ports: portset.HostPorts, tmp_path: Path
) -> None:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    root = safepaths.RuntimeRoot.adopt(base)

    reply = hardware_command.run(request(ports, root, "snapshot"))
    with pytest.raises(errors.PreconditionUnmet) as refused:
        hardware_command.run(request(ports, None, "snapshot"))

    assert isinstance(reply.document, dict)
    written = Path(str(reply.document["observations"]))
    assert written.parent.parent == base / "hardware-observations"
    assert written.name == "observations.json"
    assert ports.files.exists(safepaths.SafePath(written))
    assert refused.value.reason is refusals.RefusalReason.PATH_NOT_A_DIRECTORY


def test_an_unknown_action_stops_at_the_parser(ports: portset.HostPorts) -> None:
    with pytest.raises(SystemExit):
        hardware_command.run(request(ports, None, "reboot"))


def test_a_monitor_transcript_on_stdin_becomes_a_kept_capture(
    ports: portset.HostPorts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hardware_command.os, "geteuid", lambda: 1000)
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    root = safepaths.RuntimeRoot.adopt(base)
    held = host(ports)
    stdin = json.dumps(CALL) + "\n" + json.dumps(REPLY) + "\n"

    reply = hardware_command.run(request(held, root, "observe-fingerprint", stdin=stdin))

    assert reply.exit_code == 0
    assert isinstance(reply.document, dict)
    assert reply.document["capture_status"] == "OBSERVED"
    assert reply.document["event_count"] == 2
    directory = Path(str(reply.document["directory"]))
    assert directory.parent == base / "fingerprint-observations"
    assert held.files.exists(safepaths.SafePath(directory / "events.jsonl"))


def test_an_incomplete_capture_is_kept_and_reported_with_its_own_exit_code(
    ports: portset.HostPorts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hardware_command.os, "geteuid", lambda: 1000)
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    root = safepaths.RuntimeRoot.adopt(base)

    reply = hardware_command.run(
        request(host(ports), root, "observe-fingerprint", stdin=json.dumps(CALL) + "\n")
    )

    assert reply.exit_code == hardware_command.INCOMPLETE_EXIT_CODE
    assert isinstance(reply.document, dict)
    assert reply.document["capture_status"] == "INCOMPLETE"
    assert "incomplete" in reply.narrative


def test_the_collector_refuses_root(
    ports: portset.HostPorts, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hardware_command.os, "geteuid", lambda: 0)
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)

    with pytest.raises(errors.Refusal) as raised:
        hardware_command.run(
            request(host(ports), safepaths.RuntimeRoot.adopt(base), "observe-fingerprint")
        )

    assert raised.value.reason is refusals.RefusalReason.HOST_RUNS_AS_ROOT

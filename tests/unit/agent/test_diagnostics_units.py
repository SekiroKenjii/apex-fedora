"""The two diagnostics collectors read what the older scripts read and write only where told."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from diagnosticfixtures import DESTINATION, PUBLIC, answering, bundle, installer, laptop

from apex.adapters.fakes import fake_files, fake_process
from apex.agent import guestguard
from apex.agent.units import guest_diagnostics_unit, installer_diagnostics_unit
from apex.config import defaults
from apex.kernel import errors, refusals, safepaths


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)


def test_diagnostics_are_written_once_to_the_destination_and_returned() -> None:
    process = answering(*(tuple(argv) for argv in guest_diagnostics_unit.COMMANDS.values()))
    files = laptop()

    report = guest_diagnostics_unit.run(
        bundle(process, files), arguments={"destination": DESTINATION}
    )

    assert report["status"] == "OBSERVATION"
    assert report["written_to"] == DESTINATION
    assert report["codecs"] == {
        "/proc/asound/card0/codec#0": "Codec: Realtek ALC294\n",
        "/proc/asound/card1/codec#2": "Codec: HDMI\n",
    }
    commands = report["commands"]
    assert isinstance(commands, dict) and set(commands) == set(guest_diagnostics_unit.COMMANDS)
    assert commands["kernel"] == {"returncode": 0, "stdout": "observed\n", "stderr": ""}
    written = files.read_bytes(safepaths.SafePath(Path(DESTINATION)), limit=1 << 20)
    assert written.endswith(b"\n") and b'"status":"OBSERVATION"' in written
    assert files.mode_of(safepaths.SafePath(Path(DESTINATION))) == defaults.RECORD_MODE
    assert [tuple(call) for call in process.calls] == [
        tuple(argv) for argv in guest_diagnostics_unit.COMMANDS.values()
    ]


def test_an_existing_destination_is_never_overwritten() -> None:
    process = answering()
    files = laptop()
    files.write_atomic(safepaths.SafePath(Path(DESTINATION)), b"earlier capture\n", mode=PUBLIC)

    with pytest.raises(errors.Refusal) as caught:
        guest_diagnostics_unit.run(
            bundle(process, files), arguments={"destination": DESTINATION}
        )

    assert caught.value.reason is refusals.RefusalReason.PROBE_DESTINATION_TAKEN
    kept = files.read_bytes(safepaths.SafePath(Path(DESTINATION)), limit=64)
    assert kept == b"earlier capture\n"
    assert process.calls == []


@pytest.mark.parametrize("destination", ["relative.json", "/media/../etc/passwd", 7, None])
def test_a_destination_that_is_not_an_absolute_path_is_refused(destination: object) -> None:
    process = answering()

    with pytest.raises(errors.Refusal) as caught:
        guest_diagnostics_unit.run(
            bundle(process, laptop()), arguments={"destination": destination}  # type: ignore[dict-item]
        )

    assert caught.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_a_missing_program_is_recorded_as_an_error_and_the_rest_still_run() -> None:
    process = answering(*(tuple(argv) for argv in guest_diagnostics_unit.COMMANDS.values()))
    process.expect(("wpctl", "status"), fake_process.Reply(missing=True))

    report = guest_diagnostics_unit.run(
        bundle(process, laptop()), arguments={"destination": DESTINATION}
    )

    commands = report["commands"]
    assert isinstance(commands, dict)
    assert commands["audio"] == {"error": "wpctl: not found"}
    assert commands["sessions"] == {"returncode": 0, "stdout": "observed\n", "stderr": ""}


def test_the_installer_bundle_carries_the_older_shape_bounded_the_same_way() -> None:
    process = answering(*(tuple(argv) for argv in installer_diagnostics_unit.COMMANDS.values()))
    files = installer()

    report = installer_diagnostics_unit.run(bundle(process, files), arguments={})

    assert report["schema"] == 1
    assert report["boot_id"] == "fixture-boot"
    assert report["payload"] == {"reference": "localhost/apex-payload:" + "b" * 64}
    logs = report["logs"]
    assert isinstance(logs, dict) and set(logs) == {"anaconda.log", "storage.log", "program.log"}
    assert logs["anaconda.log"] == {
        "data": base64.b64encode(b"anaconda started\n").decode(),
        "sha256": hashlib.sha256(b"anaconda started\n").hexdigest(),
        "truncated": False,
    }
    assert logs["storage.log"] == {"error": "/tmp/storage.log: no such file"}
    observations = report["observations"]
    assert isinstance(observations, dict)
    assert list(observations) == ["preflight", *installer_diagnostics_unit.COMMANDS]
    assert observations["selinux"] == {
        "returncode": 0, "stdout": "observed\n", "stderr": "", "truncated": False,
    }
    assert [tuple(call) for call in process.calls] == [
        ("systemd-detect-virt", "--vm"),
        *(tuple(argv) for argv in installer_diagnostics_unit.COMMANDS.values()),
    ]


def test_a_log_is_read_only_when_it_is_a_regular_file_and_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(defaults, "LOG_LIMIT", type(defaults.LOG_LIMIT)(10))
    files = installer()
    program = safepaths.SafePath(Path("/tmp/program.log"))
    files.write_atomic(program, b"123456789012", mode=PUBLIC)
    files.symlink(safepaths.SafePath(Path("/tmp/storage.log")), target=program)
    ports = bundle(answering(), files)

    storage = safepaths.SafePath(Path("/tmp/storage.log"))
    long = installer_diagnostics_unit.read_log(ports, program)
    linked = installer_diagnostics_unit.read_log(ports, storage)
    absent = installer_diagnostics_unit.read_log(ports, safepaths.SafePath(Path("/tmp/absent.log")))

    assert long["truncated"] is True
    assert base64.b64decode(str(long["data"])) == b"1234567890"
    assert linked == {"error": "not a regular file"}
    assert "error" in absent


def test_the_installer_guard_checks_root_then_the_marker_then_the_hypervisor() -> None:
    process = answering()
    files = fake_files.MemoryFiles()

    with pytest.raises(errors.Refusal) as caught:
        installer_diagnostics_unit.run(bundle(process, files), arguments={})

    assert caught.value.reason is refusals.RefusalReason.PROBE_ENVIRONMENT_UNEXPECTED
    assert process.calls == []

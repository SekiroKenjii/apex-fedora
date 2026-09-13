"""The serial guest shell, driven against a real bash behind a unix socket.

The peer is this process, so the credential check is exercised for real; the shell is
bash reading the socket, so the here-documents, the markers and the base64 are exercised
against the program that will read them in the guest. What cannot be exercised here is
the console's echo, which is off in the guest and absent on a socket.
"""

from __future__ import annotations

import os
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from apex.adapters.real import real_serialshell
from apex.config import defaults
from apex.kernel import commands, errors, quantities, safepaths, timing
from apex.ports import guestshell

DEADLINE = timing.Deadline(timing.Elapsed(20))


class Console:
    """Accepts one connection at a time and hands it to a bash reading commands from it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(path))
        self._server.listen(1)
        self._server.settimeout(0.2)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stop.is_set():
            try:
                connection, _ = self._server.accept()
            except TimeoutError:
                continue
            with connection:
                wire = connection.fileno()
                shell = subprocess.Popen(
                    ["bash", "--norc", "--noprofile", "-s"],
                    stdin=wire, stdout=wire, stderr=wire,
                    env={"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/")},
                )
                shell.wait()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._server.close()


@pytest.fixture
def console(tmp_path: Path) -> Iterator[Console]:
    held = Console(tmp_path / "serial.sock")
    yield held
    held.close()


def shell(console: Console, *, process: int | None = None) -> real_serialshell.SerialGuestShell:
    return real_serialshell.SerialGuestShell(
        safepaths.SafePath(console.path),
        expected_process=os.getpid() if process is None else process,
        expected_user=os.getuid(),
    )


def target(tmp_path: Path) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user="root", port=quantities.TcpPort(22245),
        key=safepaths.SafePath(tmp_path / "unused"),
        known_hosts=safepaths.SafePath(tmp_path / "kh"),
    )


def run(script: guestshell.RemoteScript, *, stdin: bytes | None = None) -> guestshell.GuestRun:
    return guestshell.GuestRun(
        script=script, deadline=DEADLINE, limit=commands.OutputLimit.default(), stdin=stdin
    )


def test_a_script_runs_with_its_input_and_its_streams_and_exit_come_back(
    console: Console, tmp_path: Path
) -> None:
    script = guestshell.RemoteScript.of(
        guestshell.Step.of("cat"),
        guestshell.Step.of("printf", "out"),
        guestshell.Step.of("sh", "-c", "printf err >&2; exit 3"),
    )

    completed = shell(console).run(target(tmp_path), run(script, stdin=b"fed\n"))

    assert completed.exit_code == 3
    assert completed.stdout == b"fed\nout"
    assert completed.stderr == b"err"
    assert not completed.truncated


def test_a_script_that_succeeds_reports_zero_and_a_transcript_takes_the_output(
    console: Console, tmp_path: Path
) -> None:
    transcript = safepaths.SafePath(tmp_path / "transcript.log")

    completed = shell(console).run(
        target(tmp_path),
        guestshell.GuestRun(
            script=guestshell.RemoteScript.of(guestshell.Step.of("echo", "hello")),
            deadline=DEADLINE, limit=commands.OutputLimit.default(), transcript=transcript,
        ),
    )

    assert completed.succeeded and completed.stdout == b""
    assert transcript.path.read_bytes() == b"hello\n"


def test_a_file_is_sent_whole_and_checked_by_digest(console: Console, tmp_path: Path) -> None:
    local = tmp_path / "wheel.bin"
    payload = os.urandom(50_000)
    local.write_bytes(payload)
    remote = safepaths.RemotePath(str(tmp_path / "remote" / "wheel.bin"))
    (tmp_path / "remote").mkdir()

    shell(console).send(
        target(tmp_path), local=safepaths.SafePath(local), remote=remote, deadline=DEADLINE
    )

    assert Path(str(remote)).read_bytes() == payload


def test_a_send_to_a_place_the_guest_cannot_write_fails(console: Console, tmp_path: Path) -> None:
    local = tmp_path / "small.bin"
    local.write_bytes(b"x")

    with pytest.raises(errors.PortFailure):
        shell(console).send(
            target(tmp_path), local=safepaths.SafePath(local),
            remote=safepaths.RemotePath(str(tmp_path / "missing" / "dir" / "file")),
            deadline=DEADLINE,
        )


def test_a_file_and_a_directory_are_received_back(console: Console, tmp_path: Path) -> None:
    remote_dir = tmp_path / "output"
    (remote_dir / "nested").mkdir(parents=True)
    (remote_dir / "result.json").write_bytes(b'{"status": "PASS"}')
    (remote_dir / "nested" / "log.txt").write_bytes(b"lines\n")
    single = safepaths.SafePath(tmp_path / "got.json")
    tree = safepaths.SafePath(tmp_path / "got")
    tree.path.mkdir()

    shell(console).receive(
        target(tmp_path), remote=safepaths.RemotePath(str(remote_dir / "result.json")),
        into=single, recursive=False, deadline=DEADLINE,
    )
    shell(console).receive(
        target(tmp_path), remote=safepaths.RemotePath(str(remote_dir)),
        into=tree, recursive=True, deadline=DEADLINE,
    )

    assert single.path.read_bytes() == b'{"status": "PASS"}'
    assert (tree.path / "output" / "nested" / "log.txt").read_bytes() == b"lines\n"


def test_a_peer_that_is_not_the_machine_is_refused_before_anything_is_sent(
    console: Console, tmp_path: Path
) -> None:
    with pytest.raises(errors.PortFailure) as caught:
        shell(console, process=os.getpid() + 100_000).run(
            target(tmp_path), run(guestshell.RemoteScript.of(guestshell.Step.of("true")))
        )

    assert "not the machine" in caught.value.cause


def test_a_response_past_the_limit_is_refused(console: Console, tmp_path: Path) -> None:
    script = guestshell.RemoteScript.of(guestshell.Step.of("head", "-c", "20000", "/dev/zero"))

    with pytest.raises(errors.PortFailure) as caught:
        shell(console).run(
            target(tmp_path),
            guestshell.GuestRun(script=script, deadline=DEADLINE, limit=commands.OutputLimit(4096)),
        )

    assert "exceeds" in caught.value.cause


def test_a_script_that_outlives_the_deadline_is_a_port_failure(
    console: Console, tmp_path: Path
) -> None:
    started = time.monotonic()

    with pytest.raises(errors.PortFailure) as caught:
        shell(console).run(
            target(tmp_path),
            guestshell.GuestRun(
                script=guestshell.RemoteScript.of(guestshell.Step.of("sleep", "5")),
                deadline=timing.Deadline(timing.Elapsed(1)), limit=commands.OutputLimit.default(),
            ),
        )

    assert "timed out" in caught.value.cause
    assert time.monotonic() - started < 4


def test_a_socket_nobody_serves_is_a_port_failure(tmp_path: Path) -> None:
    absent = real_serialshell.SerialGuestShell(
        safepaths.SafePath(tmp_path / "absent.sock"), expected_process=os.getpid()
    )

    with pytest.raises(errors.PortFailure):
        absent.run(target(tmp_path), run(guestshell.RemoteScript.of(guestshell.Step.of("true"))))
    assert defaults.SERIAL_LOCK_NAME in {path.name for path in tmp_path.iterdir()}

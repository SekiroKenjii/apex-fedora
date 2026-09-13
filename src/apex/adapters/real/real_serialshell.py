"""The guest shell over the machine's serial socket, through the rescue shell already open there.

A live guest has no ssh; what it has is a root shell on its serial console, which the
hypervisor exposes as a unix socket. Every call opens that socket, checks that the peer is
the machine's own process, and speaks the older console's protocol: echo off, a token the
shell must print back before anything is sent, then one command whose input and files
travel as base64 in a quoted here-document and whose exit code and standard error come back
between markers carrying the same token. Nothing typed at the console is trusted without
the token, and no response is read past the caller's limit.
"""

from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import io
import os
import posixpath
import re
import secrets
import shlex
import socket
import struct
import tarfile
import time
from collections.abc import Iterator

from apex.config import defaults
from apex.kernel import bounded, claims, commands, errors, safepaths, timing
from apex.ports import guestshell

PORT = "serial"
READY = "APEXREADY"
OUT = "APEXOUT"
DONE = "APEXDONE"
ERREND = "APEXERREND"
INPUT = "APEXIN"
CHUNK = 8192
PEER_CREDENTIALS = struct.Struct("3i")


class SerialGuestShell(guestshell.GuestShellPort):
    environment = claims.EnvironmentKind.BUILD

    def __init__(
        self,
        socket_path: safepaths.SafePath,
        *,
        expected_process: int,
        expected_user: int = 0,
    ) -> None:
        self._socket_path = socket_path
        self.expected_process = expected_process
        self._expected_user = expected_user
        self._lock_path = socket_path.path.with_name(defaults.SERIAL_LOCK_NAME)

    def run(
        self, target: guestshell.GuestTarget, run: guestshell.GuestRun  # noqa: ARG002
    ) -> commands.CompletedRun:
        token = secrets.token_hex(16)
        stdin = base64.encodebytes(run.stdin or b"").decode()
        command = (
            f"base64 -d <<'{INPUT}_{token}' > /tmp/apex-in-{token}\n{stdin}{INPUT}_{token}\n"
            f"printf '\\n{OUT}:{token}\\n'; "
            f"bash -c {shlex.quote(run.script.rendered())} < /tmp/apex-in-{token} "
            f"2> /tmp/apex-err-{token}; printf '\\n{DONE}:{token}:%s\\n' \"$?\"; "
            f"base64 -w0 /tmp/apex-err-{token}; printf '\\n{ERREND}:{token}\\n'; "
            f"rm -f /tmp/apex-in-{token} /tmp/apex-err-{token}\n"
        )
        with self._session(run.deadline) as session:
            session.handshake(token)
            response = session.exchange(
                command.encode(), until=_line(ERREND, token), limit=bounded.Limit(run.limit.value)
            )
        code, stdout, stderr = _parse(response, token)
        if run.transcript is not None:
            run.transcript.path.write_bytes(stdout)
            stdout = b""
        out = bounded.take(stdout, bounded.Limit(run.limit.value))
        err = bounded.take(stderr, bounded.Limit(run.limit.value))
        return commands.CompletedRun(
            exit_code=code, stdout=out.data, stderr=err.data,
            truncated=out.truncated or err.truncated,
        )

    def send(
        self,
        target: guestshell.GuestTarget,  # noqa: ARG002
        *,
        local: safepaths.SafePath,
        remote: safepaths.RemotePath,
        deadline: timing.Deadline,
    ) -> None:
        payload = local.path.read_bytes()
        if len(payload) > defaults.SERIAL_TRANSFER_LIMIT.value:
            raise errors.PortFailure(
                port=PORT, cause=f"{local}: larger than the serial transfer limit"
            )
        token = secrets.token_hex(16)
        digest = hashlib.sha256(payload).hexdigest()
        command = (
            f"base64 -d <<'{INPUT}_{token}' > {remote} && "
            f"test \"$(sha256sum {remote} | cut -d' ' -f1)\" = {digest}\n"
            f"{base64.encodebytes(payload).decode()}{INPUT}_{token}\n"
            f"printf '\\n{DONE}:{token}:%s\\n' \"$?\"\n"
        )
        with self._session(deadline) as session:
            session.handshake(token)
            response = session.exchange(
                command.encode(), until=_done(token), limit=bounded.Limit(CHUNK)
            )
        if _code(response, token) != 0:
            raise errors.PortFailure(port=PORT, cause=f"{remote}: the guest did not take the file")

    def receive(
        self,
        target: guestshell.GuestTarget,  # noqa: ARG002
        *,
        remote: safepaths.RemotePath,
        into: safepaths.SafePath,
        recursive: bool,
        deadline: timing.Deadline,
    ) -> None:
        token = secrets.token_hex(16)
        parent, name = posixpath.split(str(remote))
        source = (
            f"tar -cf - -C {shlex.quote(parent)} {shlex.quote(name)}"
            if recursive
            else f"cat {remote}"
        )
        command = (
            f"printf '\\n{OUT}:{token}\\n'; {source} | base64 -w0; "
            f"printf '\\n{DONE}:{token}:%s\\n' \"${{PIPESTATUS[0]}}\"\n"
        )
        with self._session(deadline) as session:
            session.handshake(token)
            response = session.exchange(
                command.encode(), until=_done(token),
                limit=bounded.Limit(defaults.SERIAL_TRANSFER_LIMIT.value * 2),
            )
        if _code(response, token) != 0:
            raise errors.PortFailure(port=PORT, cause=f"{remote}: the guest could not read it")
        payload = _decode(_between(response, _line(OUT, token), _done(token)))
        if recursive:
            with tarfile.open(fileobj=io.BytesIO(payload)) as archive:
                archive.extractall(into.path, filter="data")
        else:
            into.path.write_bytes(payload)

    @contextlib.contextmanager
    def _session(self, deadline: timing.Deadline) -> Iterator[_Session]:
        lock = self._lock_path.open("a")
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise errors.PortFailure(
                    port=PORT, cause="another serial console is open on this machine"
                ) from error
            connection.settimeout(defaults.SERIAL_CONNECT_TIMEOUT.seconds)
            try:
                connection.connect(str(self._socket_path))
            except OSError as error:
                raise errors.PortFailure(
                    port=PORT, cause=f"{self._socket_path}: {error}"
                ) from error
            self._require_peer(connection)
            yield _Session(connection, deadline, expected_user=self._expected_user)
        finally:
            connection.close()
            lock.close()

    def _require_peer(self, connection: socket.socket) -> None:
        raw = connection.getsockopt(
            socket.SOL_SOCKET, socket.SO_PEERCRED, PEER_CREDENTIALS.size
        )
        process, user, _ = PEER_CREDENTIALS.unpack(raw)
        if process != self.expected_process or user != os.getuid():
            raise errors.PortFailure(
                port=PORT,
                cause=f"the serial socket's peer is process {process} of user {user}, "
                f"not the machine this lease names",
            )


class _Session:
    def __init__(
        self, connection: socket.socket, deadline: timing.Deadline, *, expected_user: int
    ) -> None:
        self._connection = connection
        self._ends_at = time.monotonic() + deadline.budget.seconds
        self._expected_user = expected_user

    def handshake(self, token: str) -> None:
        """Echo off, and the token printed back by the expected user's shell before anything."""
        probe = (
            f"\nstty -echo 2>/dev/null; test \"$(id -u)\" = {self._expected_user} && "
            f"printf '\\n{READY}:{token}\\n'\n"
        )
        self.exchange(
            probe.encode(), until=_line(READY, token), limit=bounded.Limit(CHUNK),
            budget=defaults.SERIAL_HANDSHAKE_DEADLINE.budget.seconds,
        )

    def exchange(
        self,
        payload: bytes,
        *,
        until: re.Pattern[bytes],
        limit: bounded.Limit,
        budget: float | None = None,
    ) -> bytes:
        try:
            self._connection.sendall(payload)
        except OSError as error:
            raise errors.PortFailure(port=PORT, cause=str(error)) from error
        ends_at = self._ends_at if budget is None else min(self._ends_at, time.monotonic() + budget)
        data = b""
        while time.monotonic() < ends_at:
            self._connection.settimeout(min(1.0, max(0.01, ends_at - time.monotonic())))
            try:
                chunk = self._connection.recv(CHUNK)
            except TimeoutError:
                continue
            except OSError as error:
                raise errors.PortFailure(port=PORT, cause=str(error)) from error
            if not chunk:
                raise errors.PortFailure(port=PORT, cause="the guest closed the serial channel")
            data += chunk
            if len(data) > limit.value:
                raise errors.PortFailure(
                    port=PORT, cause=f"the serial response exceeds {limit.value} bytes"
                )
            if until.search(data):
                return data
        raise errors.PortFailure(
            port=PORT, cause="the serial response timed out; inspect the retained serial log"
        )


def _line(marker: str, token: str) -> re.Pattern[bytes]:
    return re.compile(rb"\r?\n" + f"{marker}:{token}".encode() + rb"\r?\n")


def _done(token: str) -> re.Pattern[bytes]:
    return re.compile(rb"\r?\n" + f"{DONE}:{token}:".encode() + rb"(\d+)\r?\n")


def _code(response: bytes, token: str) -> int:
    found = _done(token).search(response)
    if found is None:
        raise errors.PortFailure(port=PORT, cause="the guest printed no exit code")
    return int(found.group(1))


def _between(response: bytes, start: re.Pattern[bytes], end: re.Pattern[bytes]) -> bytes:
    opened = start.search(response)
    closed = end.search(response, opened.end() if opened else 0)
    if opened is None or closed is None:
        raise errors.PortFailure(port=PORT, cause="the guest's answer lacks its markers")
    return response[opened.end():closed.start()]


def _decode(text: bytes) -> bytes:
    try:
        return base64.b64decode(b"".join(text.split()), validate=True)
    except ValueError as error:
        raise errors.PortFailure(
            port=PORT, cause=f"the guest's answer is not base64: {error}"
        ) from error


def _parse(response: bytes, token: str) -> tuple[int, bytes, bytes]:
    code = _code(response, token)
    stdout = _between(response, _line(OUT, token), _done(token))
    stderr = _decode(_between(response, _done(token), _line(ERREND, token)))
    return code, stdout, stderr

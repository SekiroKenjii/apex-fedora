"""The QEMU machine protocol over a unix socket, one line of JSON each way."""

from __future__ import annotations

import contextlib
import io
import json
import socket
from collections.abc import Iterator

from apex.config import defaults
from apex.kernel import claims, errors, safepaths, timing
from apex.ports import qmp

GREETING_KEY = "QMP"
CAPABILITIES = qmp.QmpCommand("qmp_capabilities")


class UnixQmp(qmp.QmpPort):
    environment = claims.EnvironmentKind.BUILD

    @contextlib.contextmanager
    def connect(
        self, socket_path: safepaths.SafePath, *, deadline: timing.Deadline
    ) -> Iterator[qmp.QmpSession]:
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(deadline.budget.seconds)
        try:
            connection.connect(str(socket_path))
        except OSError as error:
            connection.close()
            raise errors.PortFailure(port="qmp", cause=f"{socket_path}: {error}") from error
        stream = connection.makefile("rwb")
        try:
            session = _Session(stream)
            session.negotiate()
            yield session
        finally:
            stream.close()
            connection.close()


class _Session(qmp.QmpSession):
    def __init__(self, stream: io.BufferedRWPair) -> None:
        self._stream = stream
        self._issued = 0

    def negotiate(self) -> None:
        greeting = self._read()
        if GREETING_KEY not in greeting:
            raise errors.PortFailure(port="qmp", cause="the greeting is not a QMP greeting")
        self.execute(CAPABILITIES)

    def execute(self, command: qmp.QmpCommand) -> object:
        self._issued += 1
        identifier = f"apex-{self._issued}"
        request: dict[str, object] = {"execute": command.name, "id": identifier}
        if command.arguments:
            request["arguments"] = dict(command.arguments)
        try:
            self._stream.write(json.dumps(request).encode() + b"\n")
            self._stream.flush()
        except OSError as error:
            raise errors.PortFailure(port="qmp", cause=str(error)) from error
        while True:
            response = self._read()
            if response.get("id") != identifier:
                continue
            if "error" in response:
                raise errors.PortFailure(
                    port="qmp", cause=f"{command.name}: {response['error']}"
                )
            return response.get("return")

    def _read(self) -> dict[str, object]:
        try:
            line = self._stream.readline(defaults.QMP_LINE_LIMIT.value + 1)
        except OSError as error:
            raise errors.PortFailure(port="qmp", cause=str(error)) from error
        if not line:
            raise errors.PortFailure(port="qmp", cause="the machine closed its monitor")
        if len(line) > defaults.QMP_LINE_LIMIT.value:
            raise errors.PortFailure(port="qmp", cause="a monitor line exceeded the limit")
        try:
            loaded = json.loads(line)
        except json.JSONDecodeError as error:
            raise errors.PortFailure(port="qmp", cause=f"monitor: {error.msg}") from error
        if not isinstance(loaded, dict):
            raise errors.PortFailure(port="qmp", cause="monitor: not an object")
        return loaded

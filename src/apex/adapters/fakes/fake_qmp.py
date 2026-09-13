"""A monitor that answers from a table and records every command it was sent."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator, Mapping

from apex.kernel import claims, errors, safepaths, timing
from apex.ports import qmp


class ScriptedQmp(qmp.QmpPort, qmp.QmpSession):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(
        self, replies: Mapping[str, object] | None = None, *, reachable: bool = True
    ) -> None:
        self._replies = dict(replies or {})
        self._reachable = reachable
        self.executed: list[qmp.QmpCommand] = []
        self.connections: list[safepaths.SafePath] = []
        self._reactions: dict[str, Callable[[], None]] = {}
        self._listeners: dict[str, Callable[[qmp.QmpCommand], None]] = {}

    @classmethod
    def with_shell_probe(cls) -> ScriptedQmp:
        """The replies the shared contract suite exercises."""
        return cls({"query-status": {"status": "running"}, "system_powerdown": {}})

    def reply(self, name: str, value: object) -> None:
        self._replies[name] = value

    def react(self, name: str, effect: Callable[[], None]) -> None:
        """What the guest does when it receives the command, as a test describes it."""
        self._reactions[name] = effect

    def react_to(self, name: str, effect: Callable[[qmp.QmpCommand], None]) -> None:
        """As `react`, for an effect that depends on the command's arguments."""
        self._listeners[name] = effect

    @contextlib.contextmanager
    def connect(
        self, socket_path: safepaths.SafePath, *, deadline: timing.Deadline  # noqa: ARG002
    ) -> Iterator[qmp.QmpSession]:
        if not self._reachable:
            raise errors.PortFailure(port="qmp", cause=f"{socket_path}: Connection refused")
        self.connections.append(socket_path)
        yield self

    def execute(self, command: qmp.QmpCommand) -> object:
        self.executed.append(command)
        if command.name not in self._replies:
            raise errors.PortFailure(
                port="qmp", cause=f"{command.name}: The command has not been found"
            )
        if command.name in self._reactions:
            self._reactions[command.name]()
        if command.name in self._listeners:
            self._listeners[command.name](command)
        return self._replies[command.name]

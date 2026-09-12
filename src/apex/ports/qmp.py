"""Talking to a running machine over its monitor socket.

A session is opened for a bounded time and closed by the context manager, so a connection
cannot outlive the operation that needed it. Commands are values, and a reply is whatever the
hypervisor returned under `return`; an error from it is a port failure, not a refusal.
"""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import Mapping
from typing import Protocol

from apex.kernel import claims, safepaths, timing


@dataclasses.dataclass(frozen=True, slots=True)
class QmpCommand:
    name: str
    arguments: Mapping[str, object] = dataclasses.field(default_factory=dict)


class QmpSession(Protocol):
    def execute(self, command: QmpCommand) -> object: ...


class QmpPort(Protocol):
    environment: claims.EnvironmentKind

    def connect(
        self, socket_path: safepaths.SafePath, *, deadline: timing.Deadline
    ) -> contextlib.AbstractContextManager[QmpSession]: ...

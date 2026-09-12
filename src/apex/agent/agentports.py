"""The authority a guest unit holds: a process, the guest's files and a clock, and no more.

A guest never signs, never downloads and never takes a host lock, so those ports are not in
its bundle and a unit cannot reach for them.
"""

from __future__ import annotations

import dataclasses
from typing import Self

from apex.kernel import claims
from apex.ports import clock, files, planning, process


@dataclasses.dataclass(frozen=True, slots=True)
class AgentPorts:
    processes: process.ProcessPort
    files: files.FileSystemPort
    clock: clock.ClockPort

    @property
    def environment(self) -> claims.EnvironmentKind:
        return claims.meet(
            member.environment for member in (self.processes, self.files, self.clock)
        )

    def for_planning(self) -> Self:
        return type(self)(
            processes=planning.Refusing("processes"),
            files=planning.Refusing("files"),
            clock=planning.Refusing("clock"),
        )

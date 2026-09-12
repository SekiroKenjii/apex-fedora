"""The authority a guest unit holds: a process, the guest's files, a clock and its container
engine, and no more.

A guest never signs with the operator's key, never downloads and never takes a host lock, so
those ports are not in its bundle and a unit cannot reach for them.
"""

from __future__ import annotations

import dataclasses
from typing import Self

from apex.kernel import claims
from apex.ports import clock, containers, files, planning, process


@dataclasses.dataclass(frozen=True, slots=True)
class AgentPorts:
    processes: process.ProcessPort
    files: files.FileSystemPort
    clock: clock.ClockPort
    containers: containers.ContainerEnginePort

    @property
    def environment(self) -> claims.EnvironmentKind:
        return claims.meet(
            member.environment
            for member in (self.processes, self.files, self.clock, self.containers)
        )

    def for_planning(self) -> Self:
        return type(self)(
            processes=planning.refusing("processes"),
            files=planning.refusing("files"),
            clock=planning.refusing("clock"),
            containers=planning.refusing("containers"),
        )

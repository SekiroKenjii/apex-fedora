"""Running a program.

The signature is the enforcement. There is no shell parameter, arguments arrive as a vector,
and a deadline is required, so the 285 call sites that run without one become inexpressible.
"""

from __future__ import annotations

from typing import Protocol

from apex.kernel import claims, commands, timing


class ProcessPort(Protocol):
    environment: claims.EnvironmentKind

    def run(
        self,
        argv: commands.Argv,
        *,
        deadline: timing.Deadline,
        limit: commands.OutputLimit,
        stdin: bytes | None = None,
    ) -> commands.CompletedRun: ...

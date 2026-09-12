"""Running a program.

The signature is the enforcement. There is no shell parameter, arguments arrive as a vector,
and a deadline is a required keyword, so a run without a bound cannot be written.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from apex.kernel import claims, commands, safepaths, timing


class ProcessPort(Protocol):
    environment: claims.EnvironmentKind

    @abstractmethod
    def run(
        self,
        argv: commands.Argv,
        *,
        deadline: timing.Deadline,
        limit: commands.OutputLimit,
        stdin: bytes | None = None,
        transcript: safepaths.SafePath | None = None,
        cwd: safepaths.SafePath | None = None,
    ) -> commands.CompletedRun:
        """Run to completion under the deadline.

        With a transcript, both output streams are appended to that file as they arrive and
        the returned run carries no output, which is how a build that talks for an hour is
        kept without holding it in memory.
        """
        ...

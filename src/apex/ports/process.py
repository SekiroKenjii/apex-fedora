"""Running a program.

The signature is the enforcement. There is no shell parameter, arguments arrive as a vector,
and a deadline is a required keyword, so a run without a bound cannot be written.
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Mapping
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
        variables: Mapping[str, str] | None = None,
        dropping: frozenset[commands.Capability] = frozenset(),
    ) -> commands.CompletedRun:
        """Run to completion under the deadline.

        With a transcript, both output streams are appended to that file as they arrive and
        the returned run carries no output, which is how a build that talks for an hour is
        kept without holding it in memory. `variables` are added to the inherited environment.
        `dropping` removes capabilities from the child's bounding set before it runs; a host
        that cannot apply the restriction fails the run rather than running it unrestricted.
        """
        ...

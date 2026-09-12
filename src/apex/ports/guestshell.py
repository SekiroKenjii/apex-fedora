"""Reaching a guest over its private loopback shell.

A guest is named by where its shell answers and which key opens it, never by an address the
caller types. A command is a script of argument vectors joined by `&&`, rendered once with
shell quoting, so the remote side receives exactly the words the stages composed.
"""

from __future__ import annotations

import dataclasses
import re
import shlex
from abc import abstractmethod
from typing import Protocol, Self

from apex.kernel import claims, commands, errors, quantities, refusals, safepaths, timing
from apex.model import machines

USER_NAME = re.compile(r"[a-z_][a-z0-9_-]*")


@dataclasses.dataclass(frozen=True, slots=True)
class GuestTarget:
    user: str
    port: quantities.TcpPort
    key: safepaths.SafePath
    known_hosts: safepaths.SafePath

    def __post_init__(self) -> None:
        if not USER_NAME.fullmatch(self.user):
            raise errors.Refusal(
                refusals.RefusalReason.MALFORMED_IDENTIFIER, subject=f"guest user {self.user!r}"
            )

    @property
    def address(self) -> str:
        return f"{self.user}@{machines.LOOPBACK}"


@dataclasses.dataclass(frozen=True, slots=True)
class Step:
    """One command in a remote script. The two flags are the only shell syntax admitted."""

    argv: commands.Argv
    quiet_errors: bool = False
    tolerated: bool = False

    @classmethod
    def of(cls, *arguments: str) -> Self:
        return cls(commands.Argv.of(*arguments))

    def rendered(self) -> str:
        text = shlex.join(self.argv)
        if self.quiet_errors:
            text += " 2>/dev/null"
        if self.tolerated:
            text += " || true"
        return text


@dataclasses.dataclass(frozen=True, slots=True)
class RemoteScript:
    steps: tuple[Step, ...]

    @classmethod
    def of(cls, *steps: Step) -> Self:
        if not steps:
            raise errors.Refusal(
                refusals.RefusalReason.SHELL_STRING_NOT_ACCEPTED,
                subject="RemoteScript",
                remedy="a script needs at least one step",
            )
        return cls(tuple(steps))

    def rendered(self) -> str:
        return " && ".join(step.rendered() for step in self.steps)

    def under_lock(self, lock: safepaths.RemotePath) -> Step:
        """The whole script as one step that holds the guest's build lock while it runs."""
        return Step.of("sudo", "flock", "-n", str(lock), "bash", "-c", self.rendered())


@dataclasses.dataclass(frozen=True, slots=True)
class GuestRun:
    script: RemoteScript
    deadline: timing.Deadline
    limit: commands.OutputLimit
    transcript: safepaths.SafePath | None = None


class GuestShellPort(Protocol):
    environment: claims.EnvironmentKind

    @abstractmethod
    def run(self, target: GuestTarget, run: GuestRun) -> commands.CompletedRun: ...

    @abstractmethod
    def send(
        self,
        target: GuestTarget,
        *,
        local: safepaths.SafePath,
        remote: safepaths.RemotePath,
        deadline: timing.Deadline,
    ) -> None: ...

    @abstractmethod
    def receive(
        self,
        target: GuestTarget,
        *,
        remote: safepaths.RemotePath,
        into: safepaths.SafePath,
        recursive: bool,
        deadline: timing.Deadline,
    ) -> None: ...

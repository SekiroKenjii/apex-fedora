"""Commands as argument vectors. There is no constructor taking a shell string."""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Iterator, Sequence

from apex.kernel import bounded, errors, refusals, timing


@dataclasses.dataclass(frozen=True, slots=True)
class OutputLimit:
    value: int

    @classmethod
    def default(cls) -> OutputLimit:
        return cls(bounded.CAPTURE_LIMIT.value)


@dataclasses.dataclass(frozen=True, slots=True)
class Argv:
    arguments: tuple[str, ...]

    @classmethod
    def of(cls, *arguments: str | os.PathLike[str]) -> Argv:
        if not arguments:
            raise errors.Refusal(
                refusals.RefusalReason.SHELL_STRING_NOT_ACCEPTED,
                subject="Argv",
                remedy="name the program to run",
            )
        return cls(tuple(os.fspath(item) for item in arguments))

    def __iter__(self) -> Iterator[str]:
        return iter(self.arguments)

    def __len__(self) -> int:
        return len(self.arguments)

    def extended(self, *arguments: str | os.PathLike[str]) -> Argv:
        return Argv(self.arguments + tuple(os.fspath(item) for item in arguments))


@dataclasses.dataclass(frozen=True, slots=True)
class GuestCommand:
    argv: Argv
    deadline: timing.Deadline
    limit: OutputLimit


@dataclasses.dataclass(frozen=True, slots=True)
class PlannedCommand:
    argv: Argv
    redacted: Sequence[str] = ()

    @property
    def rendered(self) -> str:
        hidden = set(self.redacted)
        return " ".join("<redacted>" if item in hidden else item for item in self.argv)


@dataclasses.dataclass(frozen=True, slots=True)
class CompletedRun:
    exit_code: int
    stdout: bytes
    stderr: bytes
    truncated: bool

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0

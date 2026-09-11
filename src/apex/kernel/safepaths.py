"""Paths that carry proof of their own validation.

Because the process, filesystem and hypervisor ports accept nothing else, the pattern of
checking a path and then using the unchecked original cannot be written.
"""

from __future__ import annotations

import dataclasses
import posixpath
import re
import stat
from collections.abc import Sequence
from pathlib import Path
from typing import Self

from apex.kernel import errors, quantities, refusals

PRIVATE_DIRECTORY_MODE = quantities.FileMode(0o700)
_SAFE_REMOTE_PATH = re.compile(r"/[A-Za-z0-9._/-]*")
# A comma separates QEMU device options, so a comma inside a path silently becomes a new
# option. Refusing it here is cheaper than quoting correctly at every call site.
OPTION_SEPARATOR = ","


@dataclasses.dataclass(frozen=True, slots=True)
class RuntimeRoot:
    path: Path

    @classmethod
    def resolve(cls, candidate: Path, *, permitted: Sequence[Path]) -> Self:
        resolved = candidate.expanduser().resolve()
        if not any(resolved.is_relative_to(base.resolve()) for base in permitted):
            raise errors.Refusal(
                refusals.RefusalReason.RUNTIME_ROOT_NOT_PERMITTED,
                subject=str(resolved),
                remedy="choose a location below one of the permitted bases",
            )
        if not resolved.is_dir():
            raise errors.Refusal(
                refusals.RefusalReason.PATH_NOT_A_DIRECTORY, subject=str(resolved)
            )
        observed = stat.S_IMODE(resolved.stat().st_mode)
        if observed != PRIVATE_DIRECTORY_MODE.value:
            raise errors.Refusal(
                refusals.RefusalReason.RUNTIME_ROOT_NOT_PRIVATE,
                subject=f"{resolved} is {observed:04o}",
                remedy="the runtime root must be 0700",
            )
        return cls(resolved)

    @classmethod
    def adopt(cls, path: Path) -> Self:
        """Accept a directory the caller already created, after checking it is private.

        This exists so a test and the composition root can hand in a directory they made
        themselves. It still checks, because a root accepted without checking would make
        every containment rule below it optional.
        """
        if path.is_symlink():
            raise errors.Refusal(
                refusals.RefusalReason.PATH_IS_A_SYMLINK, subject=str(path)
            )
        resolved = path.resolve()
        if not resolved.is_dir():
            raise errors.Refusal(
                refusals.RefusalReason.PATH_NOT_A_DIRECTORY, subject=str(path)
            )
        observed = stat.S_IMODE(resolved.stat().st_mode)
        if observed != PRIVATE_DIRECTORY_MODE.value:
            raise errors.Refusal(
                refusals.RefusalReason.RUNTIME_ROOT_NOT_PRIVATE,
                subject=f"{resolved} is {observed:04o}",
                remedy="the runtime root must be 0700",
            )
        return cls(resolved)

    def child(self, relative: str) -> SafePath:
        target = (self.path / relative).resolve()
        if not target.is_relative_to(self.path):
            raise errors.Refusal(
                refusals.RefusalReason.PATH_OUTSIDE_RUNTIME_ROOT, subject=relative
            )
        return SafePath(target)


@dataclasses.dataclass(frozen=True, slots=True)
class SafePath:
    path: Path

    def __post_init__(self) -> None:
        if OPTION_SEPARATOR in str(self.path):
            raise errors.Refusal(
                refusals.RefusalReason.PATH_CONTAINS_OPTION_SEPARATOR, subject=str(self.path)
            )

    @classmethod
    def regular_file(cls, candidate: Path, *, within: RuntimeRoot) -> Self:
        if candidate.is_symlink():
            raise errors.Refusal(
                refusals.RefusalReason.PATH_IS_A_SYMLINK, subject=str(candidate)
            )
        resolved = candidate.resolve()
        if not resolved.is_relative_to(within.path):
            raise errors.Refusal(
                refusals.RefusalReason.PATH_OUTSIDE_RUNTIME_ROOT, subject=str(candidate)
            )
        if not resolved.is_file():
            raise errors.Refusal(
                refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE, subject=str(candidate)
            )
        return cls(resolved)

    def __str__(self) -> str:
        return str(self.path)

    def __fspath__(self) -> str:
        return str(self.path)


@dataclasses.dataclass(frozen=True, slots=True)
class RegularFile:
    """A regular, non-symlink file the caller may read from anywhere on the host.

    A trust anchor is the operator's key wherever they keep it; a source file is in the
    checkout. Neither lives under the runtime root, and neither is ever written through.
    """

    path: Path

    @classmethod
    def adopt(cls, candidate: Path) -> Self:
        if candidate.is_symlink():
            raise errors.Refusal(
                refusals.RefusalReason.PATH_IS_A_SYMLINK, subject=str(candidate)
            )
        resolved = candidate.resolve()
        if not resolved.is_file():
            raise errors.Refusal(
                refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE, subject=str(candidate)
            )
        return cls(resolved)

    def __str__(self) -> str:
        return str(self.path)

    def __fspath__(self) -> str:
        return str(self.path)


@dataclasses.dataclass(frozen=True, slots=True)
class SourceRoot:
    """A directory sources are read from. Nothing is written below it, so any mode will do."""

    path: Path

    @classmethod
    def adopt(cls, path: Path) -> Self:
        if path.is_symlink():
            raise errors.Refusal(
                refusals.RefusalReason.PATH_IS_A_SYMLINK, subject=str(path)
            )
        resolved = path.resolve()
        if not resolved.is_dir():
            raise errors.Refusal(
                refusals.RefusalReason.PATH_NOT_A_DIRECTORY, subject=str(path)
            )
        return cls(resolved)


@dataclasses.dataclass(frozen=True, slots=True)
class RemotePath:
    value: str

    def __post_init__(self) -> None:
        if not _SAFE_REMOTE_PATH.fullmatch(self.value):
            raise errors.Refusal(
                refusals.RefusalReason.SHELL_STRING_NOT_ACCEPTED,
                subject=self.value,
                remedy="use an absolute path without whitespace or shell metacharacters",
            )

    def __str__(self) -> str:
        return self.value

    def joined(self, name: str) -> Self:
        return type(self)(posixpath.join(self.value, name))

"""Reading and writing files.

The mode is a required keyword on every write, so the permission a runtime document lands with
is a decision at the call site rather than a side effect of how the file was created.
"""

from __future__ import annotations

import dataclasses
import enum
from abc import abstractmethod
from typing import Protocol

from apex.kernel import claims, identifiers, quantities, safepaths


class EntryKind(enum.StrEnum):
    REGULAR = "regular"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"


@dataclasses.dataclass(frozen=True, slots=True)
class TreeEntry:
    relative: str
    kind: EntryKind


class FileSystemPort(Protocol):
    environment: claims.EnvironmentKind

    @abstractmethod
    def read_bytes(self, path: safepaths.SafePath, *, limit: int) -> bytes: ...

    @abstractmethod
    def write_atomic(
        self, path: safepaths.SafePath, payload: bytes, *, mode: quantities.FileMode
    ) -> identifiers.Digest: ...

    @abstractmethod
    def append_line(
        self, path: safepaths.SafePath, payload: bytes, *, mode: quantities.FileMode
    ) -> None:
        """Append one newline-terminated record durably.

        An append-only log cannot be built out of read-modify-write, so this is a distinct
        operation rather than a convenience over `write_atomic`.
        """
        ...

    @abstractmethod
    def make_directory(self, path: safepaths.SafePath, *, mode: quantities.FileMode) -> None:
        """Create the directory and any missing parent, each with the given mode."""
        ...

    @abstractmethod
    def copy(self, source: safepaths.SafePath, destination: safepaths.SafePath) -> None:
        """Copy one regular file's bytes; the destination's mode is the source's."""
        ...

    @abstractmethod
    def link(self, existing: safepaths.SafePath, new: safepaths.SafePath) -> None:
        """A second name for the same bytes, refused when the new name is taken."""
        ...

    @abstractmethod
    def reserve(self, path: safepaths.SafePath, *, size: quantities.ByteCount) -> None:
        """A new sparse file of the given size, refused when the path is taken."""
        ...

    @abstractmethod
    def remove(self, path: safepaths.SafePath) -> None:
        """Remove one regular file. A directory is never removed through this port."""
        ...

    @abstractmethod
    def free_space(self, path: safepaths.SafePath) -> quantities.ByteCount: ...

    @abstractmethod
    def exists(self, path: safepaths.SafePath) -> bool: ...

    @abstractmethod
    def mode_of(self, path: safepaths.SafePath) -> quantities.FileMode: ...

    @abstractmethod
    def list_tree(self, directory: safepaths.SafePath) -> tuple[TreeEntry, ...]:
        """Every entry below a directory, symlinks reported as symlinks and never followed."""
        ...

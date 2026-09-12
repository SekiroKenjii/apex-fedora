"""Reading and writing files.

The mode is a required keyword on every write, so the permission a runtime document lands with
is a decision at the call site rather than a side effect of how the file was created.
"""

from __future__ import annotations

import dataclasses
import enum
from abc import abstractmethod
from typing import Protocol

from apex.kernel import claims, errors, identifiers, quantities, refusals, safepaths


class EntryKind(enum.StrEnum):
    REGULAR = "regular"
    DIRECTORY = "directory"
    SYMLINK = "symlink"
    OTHER = "other"


@dataclasses.dataclass(frozen=True, slots=True)
class TreeEntry:
    relative: str
    kind: EntryKind


@dataclasses.dataclass(frozen=True, slots=True)
class DeviceNumber:
    """The kernel's name for a device node; sysfs spells it `major:minor`."""

    major: int
    minor: int

    @classmethod
    def parse(cls, text: str) -> DeviceNumber:
        major, separator, minor = text.strip().partition(":")
        if not separator or not major.isdigit() or not minor.isdigit():
            raise errors.Refusal(
                refusals.RefusalReason.MALFORMED_DEVICE_NUMBER, subject=text.strip()
            )
        return cls(int(major), int(minor))

    @property
    def rendered(self) -> str:
        return f"{self.major}:{self.minor}"


@dataclasses.dataclass(frozen=True, slots=True)
class Inspection:
    """What `lstat` and the security label say about one path, without following a link.

    `device` is the number of a block or character node and nothing else, so a caller that
    wants to know a node is the device sysfs described compares one field.
    """

    kind: EntryKind
    owner: int
    group: int
    mode: quantities.FileMode
    label: str | None
    device: DeviceNumber | None


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
    def reserve(
        self, path: safepaths.SafePath, *, size: quantities.ByteCount, mode: quantities.FileMode
    ) -> None:
        """A new sparse file of the given size and mode, refused when the path is taken."""
        ...

    @abstractmethod
    def patch(self, path: safepaths.SafePath, *, offset: int, payload: bytes) -> None:
        """Overwrite bytes in place, in the same inode. Exists for one self test."""
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

    @abstractmethod
    def list_directory(self, directory: safepaths.SafePath) -> tuple[TreeEntry, ...]:
        """The entries of one directory only, sorted by name, symlinks never followed."""
        ...

    @abstractmethod
    def resolve(self, path: safepaths.SafePath) -> safepaths.SafePath:
        """The path with every symlink followed; refused when any link is dangling."""
        ...

    @abstractmethod
    def inspect(self, path: safepaths.SafePath) -> Inspection: ...

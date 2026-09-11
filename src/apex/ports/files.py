"""Reading and writing files.

The mode is a required keyword on every write, so the permission a runtime document lands with
is a decision at the call site rather than a side effect of how the file was created.
"""

from __future__ import annotations

from typing import Protocol

from apex.kernel import claims, identifiers, quantities, safepaths


class FileSystemPort(Protocol):
    environment: claims.EnvironmentKind

    def read_bytes(self, path: safepaths.SafePath, *, limit: int) -> bytes: ...

    def write_atomic(
        self, path: safepaths.SafePath, payload: bytes, *, mode: quantities.FileMode
    ) -> identifiers.Digest: ...

    def append_line(
        self, path: safepaths.SafePath, payload: bytes, *, mode: quantities.FileMode
    ) -> None:
        """Append one newline-terminated record durably.

        An append-only log cannot be built out of read-modify-write, so this is a distinct
        operation rather than a convenience over `write_atomic`.
        """
        ...

    def exists(self, path: safepaths.SafePath) -> bool: ...

    def mode_of(self, path: safepaths.SafePath) -> quantities.FileMode: ...

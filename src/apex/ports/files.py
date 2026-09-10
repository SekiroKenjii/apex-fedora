"""Reading and writing files.

The mode is a required keyword on every write. Today the runtime documents land at 0600 by
accident of how a temporary file is created, which means the property holds until someone
changes the helper.
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

    def exists(self, path: safepaths.SafePath) -> bool: ...

    def mode_of(self, path: safepaths.SafePath) -> quantities.FileMode: ...

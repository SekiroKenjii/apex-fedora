"""A digest port over an in-memory file port, for units that hash what they wrote."""

from __future__ import annotations

from apex.kernel import claims, hashing, identifiers, safepaths
from apex.ports import digesting, files


class MemoryDigests(digesting.DigestPort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self, filesystem: files.FileSystemPort) -> None:
        self.filesystem = filesystem
        self.reads = 0

    def file(self, path: safepaths.SafePath) -> identifiers.Digest:
        self.reads += 1
        return hashing.digest_bytes(self.filesystem.read_bytes(path, limit=1 << 30))

    def forget(self) -> None:
        return None

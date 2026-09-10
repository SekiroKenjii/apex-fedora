"""An in-memory tree that records every write and its mode."""

from __future__ import annotations

import dataclasses

from apex.kernel import bounded, claims, errors, hashing, identifiers, quantities, safepaths


@dataclasses.dataclass(frozen=True, slots=True)
class StoredFile:
    payload: bytes
    mode: quantities.FileMode


class MemoryFiles:
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self) -> None:
        self._files: dict[str, StoredFile] = {}
        self.writes: list[str] = []

    def read_bytes(self, path: safepaths.SafePath, *, limit: int) -> bytes:
        stored = self._files.get(str(path))
        if stored is None:
            raise errors.PortFailure(port="files", cause=f"{path}: no such file")
        return bounded.take(stored.payload, bounded.Limit(limit)).data

    def write_atomic(
        self, path: safepaths.SafePath, payload: bytes, *, mode: quantities.FileMode
    ) -> identifiers.Digest:
        self._files[str(path)] = StoredFile(payload, mode)
        self.writes.append(str(path))
        return hashing.digest_bytes(payload)

    def exists(self, path: safepaths.SafePath) -> bool:
        return str(path) in self._files

    def mode_of(self, path: safepaths.SafePath) -> quantities.FileMode:
        stored = self._files.get(str(path))
        if stored is None:
            raise errors.PortFailure(port="files", cause=f"{path}: no such file")
        return stored.mode

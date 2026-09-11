"""An in-memory tree that records every write and its mode."""

from __future__ import annotations

import dataclasses

from apex.kernel import bounded, claims, errors, hashing, identifiers, quantities, safepaths
from apex.ports import files


@dataclasses.dataclass(frozen=True, slots=True)
class StoredFile:
    payload: bytes
    mode: quantities.FileMode


class MemoryFiles:
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self, *, fail_after: int | None = None) -> None:
        self._files: dict[str, StoredFile] = {}
        self.directories: set[str] = set()
        self.writes: list[str] = []
        self.appended = 0
        self.fail_after = fail_after

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

    def append_line(
        self, path: safepaths.SafePath, payload: bytes, *, mode: quantities.FileMode
    ) -> None:
        if self.fail_after is not None and self.appended >= self.fail_after:
            raise errors.PortFailure(port="files", cause="the device is full")
        existing = self._files.get(str(path))
        body = (existing.payload if existing else b"") + payload + b"\n"
        self._files[str(path)] = StoredFile(body, existing.mode if existing else mode)
        self.appended += 1

    def exists(self, path: safepaths.SafePath) -> bool:
        return str(path) in self._files

    def mode_of(self, path: safepaths.SafePath) -> quantities.FileMode:
        stored = self._files.get(str(path))
        if stored is None:
            raise errors.PortFailure(port="files", cause=f"{path}: no such file")
        return stored.mode

    def list_tree(self, directory: safepaths.SafePath) -> tuple[files.TreeEntry, ...]:
        prefix = str(directory).rstrip("/") + "/"
        found: dict[str, files.EntryKind] = {}
        for stored in self._files:
            if not stored.startswith(prefix):
                continue
            relative = stored[len(prefix):]
            parts = relative.split("/")
            for depth in range(1, len(parts)):
                found.setdefault("/".join(parts[:depth]), files.EntryKind.DIRECTORY)
            found[relative] = files.EntryKind.REGULAR
        if not found and str(directory) not in self.directories:
            raise errors.PortFailure(port="files", cause=f"{directory}: not a directory")
        return tuple(
            files.TreeEntry(relative=name, kind=kind) for name, kind in sorted(found.items())
        )

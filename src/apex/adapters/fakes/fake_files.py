"""An in-memory tree that records every write and its mode."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from apex.kernel import bounded, claims, errors, hashing, identifiers, quantities, safepaths
from apex.ports import files


@dataclasses.dataclass(frozen=True, slots=True)
class StoredFile:
    """Bytes at rest; an appended file keeps a growing buffer so appending stays linear."""

    payload: bytes | bytearray
    mode: quantities.FileMode


class MemoryFiles(files.FileSystemPort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self, *, fail_after: int | None = None) -> None:
        self._files: dict[str, StoredFile] = {}
        self.directories: set[str] = set()
        self.writes: list[str] = []
        self.appended = 0
        self.fail_after = fail_after
        self.reserved: dict[str, quantities.ByteCount] = {}
        self.free = quantities.Gib(512).as_bytes()
        self.links: dict[str, str] = {}
        self.labels: dict[str, str] = {}
        self.devices: dict[str, files.DeviceNumber] = {}
        self._inodes: dict[str, int] = {}
        self._versions: dict[str, int] = {}
        self._issued = 0

    def _fresh_inode(self, name: str) -> None:
        self._issued += 1
        self._inodes[name] = self._issued
        self._versions[name] = self._issued

    def _canonical(self, name: str) -> str:
        """Follow a link anywhere on the path, as the kernel would for a read."""
        for _ in range(len(self.links) + 1):
            for source, target in self.links.items():
                if name == source or name.startswith(source + "/"):
                    name = target + name[len(source):]
                    break
            else:
                return name
        return name

    def read_bytes(self, path: safepaths.SafePath, *, limit: int) -> bytes:
        stored = self._files.get(self._canonical(str(path)))
        if stored is None:
            raise errors.PortFailure(port="files", cause=f"{path}: no such file")
        return bounded.take(bytes(stored.payload), bounded.Limit(limit)).data

    def write_atomic(
        self, path: safepaths.SafePath, payload: bytes, *, mode: quantities.FileMode
    ) -> identifiers.Digest:
        self._files[str(path)] = StoredFile(payload, mode)
        self._fresh_inode(str(path))
        self.writes.append(str(path))
        return hashing.digest_bytes(payload)

    def append_line(
        self, path: safepaths.SafePath, payload: bytes, *, mode: quantities.FileMode
    ) -> None:
        if self.fail_after is not None and self.appended >= self.fail_after:
            raise errors.PortFailure(port="files", cause="the device is full")
        existing = self._files.get(str(path))
        if existing is None:
            buffer = bytearray()
        elif isinstance(existing.payload, bytearray):
            buffer = existing.payload
        else:
            buffer = bytearray(existing.payload)
        buffer += payload + b"\n"
        self._files[str(path)] = StoredFile(buffer, existing.mode if existing else mode)
        self.appended += 1

    def make_directory(self, path: safepaths.SafePath, *, mode: quantities.FileMode) -> None:  # noqa: ARG002
        self.directories.add(str(path))

    def copy(self, source: safepaths.SafePath, destination: safepaths.SafePath) -> None:
        stored = self._files.get(str(source))
        if stored is None:
            raise errors.PortFailure(port="files", cause=f"{source}: no such file")
        self._files[str(destination)] = StoredFile(bytes(stored.payload), stored.mode)
        self._fresh_inode(str(destination))
        self.writes.append(str(destination))

    def link(self, existing: safepaths.SafePath, new: safepaths.SafePath) -> None:
        if str(new) in self._files:
            raise errors.PortFailure(port="files", cause=f"{new}: File exists")
        self.copy(existing, new)
        self._inodes[str(new)] = self._inodes[str(existing)]
        self._versions[str(new)] = self._versions[str(existing)]

    def reserve(
        self, path: safepaths.SafePath, *, size: quantities.ByteCount, mode: quantities.FileMode
    ) -> None:
        if str(path) in self._files:
            raise errors.PortFailure(port="files", cause=f"{path}: File exists")
        self._files[str(path)] = StoredFile(b"", mode)
        self.reserved[str(path)] = size
        self.writes.append(str(path))

    def patch(self, path: safepaths.SafePath, *, offset: int, payload: bytes) -> None:
        stored = self._files.get(str(path))
        if stored is None:
            raise errors.PortFailure(port="files", cause=f"{path}: no such file")
        body = bytearray(stored.payload)
        body[offset : offset + len(payload)] = payload
        self._files[str(path)] = StoredFile(bytes(body), stored.mode)

    def remove(self, path: safepaths.SafePath) -> None:
        if str(path) not in self._files:
            raise errors.PortFailure(port="files", cause=f"{path}: no such file")
        del self._files[str(path)]
        self._inodes.pop(str(path), None)

    def identity(self, path: safepaths.SafePath) -> files.FileIdentity:
        name = str(path)
        stored = self._files.get(name)
        if stored is None:
            raise errors.PortFailure(port="files", cause=f"{path}: no such file")
        inode = self._inodes[name]
        return files.FileIdentity(
            device=1, inode=inode, size=len(stored.payload),
            modified_nanoseconds=self._versions[name],
            links=sum(1 for held in self._inodes.values() if held == inode),
            allocated=len(stored.payload),
        )

    def replace(self, source: safepaths.SafePath, destination: safepaths.SafePath) -> None:
        stored = self._files.get(str(source))
        if stored is None:
            raise errors.PortFailure(port="files", cause=f"{source}: no such file")
        self._files[str(destination)] = stored
        self._inodes[str(destination)] = self._inodes[str(source)]
        self._versions[str(destination)] = self._versions[str(source)]
        del self._files[str(source)]
        del self._inodes[str(source)]
        self.writes.append(str(destination))

    def free_space(self, path: safepaths.SafePath) -> quantities.ByteCount:  # noqa: ARG002
        return self.free

    def exists(self, path: safepaths.SafePath) -> bool:
        name = self._canonical(str(path))
        if name in self._files or name in self.directories or name in self.devices:
            return True
        return any(stored.startswith(name + "/") for stored in self._files)

    def mode_of(self, path: safepaths.SafePath) -> quantities.FileMode:
        stored = self._files.get(str(path))
        if stored is None:
            raise errors.PortFailure(port="files", cause=f"{path}: no such file")
        return stored.mode

    def list_directory(self, directory: safepaths.SafePath) -> tuple[files.TreeEntry, ...]:
        prefix = self._canonical(str(directory)).rstrip("/") + "/"
        found: dict[str, files.EntryKind] = {}
        for name in self._files:
            if name.startswith(prefix):
                head, _, rest = name[len(prefix):].partition("/")
                found.setdefault(
                    head, files.EntryKind.DIRECTORY if rest else files.EntryKind.REGULAR
                )
        direct = [
            (name[len(prefix):], kind)
            for names, kind in (
                (self.directories, files.EntryKind.DIRECTORY),
                (self.devices, files.EntryKind.OTHER),
                (self.links, files.EntryKind.SYMLINK),
            )
            for name in names
            if name.startswith(prefix) and "/" not in name[len(prefix):]
        ]
        for name, kind in direct:
            found[name] = kind
        if not found and prefix.rstrip("/") not in self.directories:
            raise errors.PortFailure(port="files", cause=f"{directory}: not a directory")
        return tuple(
            files.TreeEntry(relative=name, kind=kind) for name, kind in sorted(found.items())
        )

    def symlink(self, path: safepaths.SafePath, *, target: safepaths.SafePath) -> None:
        """A link the fake will follow; the real adapter finds these on disk."""
        self.links[str(path)] = str(target)

    def resolve(self, path: safepaths.SafePath) -> safepaths.SafePath:
        current = str(path)
        for _ in range(len(self.links) + 1):
            target = self.links.get(current)
            if target is None:
                if self.exists(safepaths.SafePath(Path(current))):
                    return safepaths.SafePath(Path(current))
                raise errors.PortFailure(port="files", cause=f"{path}: no such file")
            current = target
        raise errors.PortFailure(port="files", cause=f"{path}: too many levels of links")

    def inspect(self, path: safepaths.SafePath) -> files.Inspection:
        name = str(path)
        if name in self.links:
            return files.Inspection(
                kind=files.EntryKind.SYMLINK, owner=0, group=0,
                mode=quantities.FileMode(0o777), label=self.labels.get(name), device=None,
            )
        if name in self.devices:
            return files.Inspection(
                kind=files.EntryKind.OTHER, owner=0, group=0,
                mode=quantities.FileMode(0o660), label=self.labels.get(name),
                device=self.devices[name],
            )
        if name in self.directories:
            return files.Inspection(
                kind=files.EntryKind.DIRECTORY, owner=0, group=0,
                mode=quantities.FileMode(0o700), label=self.labels.get(name), device=None,
            )
        stored = self._files.get(name)
        if stored is None:
            raise errors.PortFailure(port="files", cause=f"{path}: no such file")
        return files.Inspection(
            kind=files.EntryKind.REGULAR, owner=0, group=0, mode=stored.mode,
            label=self.labels.get(name), device=None,
        )

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

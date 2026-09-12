"""Atomic writes that leave nothing behind and never widen a mode."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from apex.kernel import bounded, claims, errors, hashing, identifiers, quantities, safepaths
from apex.ports import files


class LocalFiles(files.FileSystemPort):
    environment = claims.EnvironmentKind.BUILD

    def read_bytes(self, path: safepaths.SafePath, *, limit: int) -> bytes:
        try:
            with path.path.open("rb") as handle:
                return bounded.take(handle.read(limit + 1), bounded.Limit(limit)).data
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error

    def write_atomic(
        self, path: safepaths.SafePath, payload: bytes, *, mode: quantities.FileMode
    ) -> identifiers.Digest:
        directory = path.path.parent
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, name = tempfile.mkstemp(dir=directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(mode.value)
            temporary.replace(path.path)
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error
        finally:
            temporary.unlink(missing_ok=True)
        self._fsync_directory(directory)
        return hashing.digest_bytes(payload)

    def _fsync_directory(self, directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def append_line(
        self, path: safepaths.SafePath, payload: bytes, *, mode: quantities.FileMode
    ) -> None:
        directory = path.path.parent
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        existed = path.path.exists()
        try:
            descriptor = os.open(
                path.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, mode.value
            )
            try:
                os.write(descriptor, payload + b"\n")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            if not existed:
                self._fsync_directory(directory)
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error

    def make_directory(self, path: safepaths.SafePath, *, mode: quantities.FileMode) -> None:
        try:
            path.path.mkdir(parents=True, exist_ok=True, mode=mode.value)
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error

    def copy(self, source: safepaths.SafePath, destination: safepaths.SafePath) -> None:
        try:
            shutil.copyfile(source.path, destination.path)
            destination.path.chmod(source.path.stat().st_mode & quantities.PERMISSION_BITS)
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error

    def link(self, existing: safepaths.SafePath, new: safepaths.SafePath) -> None:
        try:
            os.link(existing.path, new.path)
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error

    def reserve(self, path: safepaths.SafePath, *, size: quantities.ByteCount) -> None:
        try:
            with path.path.open("xb") as handle:
                handle.truncate(size.value)
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error

    def free_space(self, path: safepaths.SafePath) -> quantities.ByteCount:
        try:
            return quantities.ByteCount(shutil.disk_usage(path.path).free)
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error

    def exists(self, path: safepaths.SafePath) -> bool:
        return path.path.exists()

    def mode_of(self, path: safepaths.SafePath) -> quantities.FileMode:
        return quantities.FileMode(path.path.stat().st_mode & 0o777)

    def list_tree(self, directory: safepaths.SafePath) -> tuple[files.TreeEntry, ...]:
        base = directory.path
        if not base.is_dir():
            raise errors.PortFailure(port="files", cause=f"{directory}: not a directory")
        entries = []
        for path in sorted(base.rglob("*")):
            entries.append(
                files.TreeEntry(relative=str(path.relative_to(base)), kind=_kind_of(path))
            )
        return tuple(entries)


def _kind_of(path: Path) -> files.EntryKind:
    if path.is_symlink():
        return files.EntryKind.SYMLINK
    if path.is_dir():
        return files.EntryKind.DIRECTORY
    if path.is_file():
        return files.EntryKind.REGULAR
    return files.EntryKind.OTHER

"""Atomic writes that leave nothing behind and never widen a mode."""

from __future__ import annotations

import errno
import os
import shutil
import stat
import tempfile
from pathlib import Path

from apex.kernel import bounded, claims, errors, hashing, identifiers, quantities, safepaths
from apex.ports import files

SECURITY_LABEL = "security.selinux"
NO_LABEL = frozenset({errno.ENODATA, errno.ENOTSUP, errno.EOPNOTSUPP})


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

    def reserve(
        self, path: safepaths.SafePath, *, size: quantities.ByteCount, mode: quantities.FileMode
    ) -> None:
        try:
            with path.path.open("xb") as handle:
                os.fchmod(handle.fileno(), mode.value)
                handle.truncate(size.value)
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error

    def patch(self, path: safepaths.SafePath, *, offset: int, payload: bytes) -> None:
        try:
            with path.path.open("r+b") as handle:
                handle.seek(offset)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error

    def remove(self, path: safepaths.SafePath) -> None:
        try:
            path.path.unlink()
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

    def list_directory(self, directory: safepaths.SafePath) -> tuple[files.TreeEntry, ...]:
        base = directory.path
        if not base.is_dir():
            raise errors.PortFailure(port="files", cause=f"{directory}: not a directory")
        try:
            names = sorted(entry.name for entry in base.iterdir())
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error
        return tuple(
            files.TreeEntry(relative=name, kind=_kind_of(base / name)) for name in names
        )

    def resolve(self, path: safepaths.SafePath) -> safepaths.SafePath:
        try:
            return safepaths.SafePath(path.path.resolve(strict=True))
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error

    def inspect(self, path: safepaths.SafePath) -> files.Inspection:
        try:
            info = path.path.lstat()
            label = _label_of(path.path)
        except OSError as error:
            raise errors.PortFailure(port="files", cause=str(error)) from error
        device = None
        if stat.S_ISBLK(info.st_mode) or stat.S_ISCHR(info.st_mode):
            device = files.DeviceNumber(os.major(info.st_rdev), os.minor(info.st_rdev))
        return files.Inspection(
            kind=_kind_of(path.path),
            owner=info.st_uid,
            group=info.st_gid,
            mode=quantities.FileMode(stat.S_IMODE(info.st_mode)),
            label=label,
            device=device,
        )


def _label_of(path: Path) -> str | None:
    try:
        raw = os.getxattr(path, SECURITY_LABEL, follow_symlinks=False)
    except OSError as error:
        if error.errno in NO_LABEL:
            return None
        raise
    return raw.rstrip(b"\0").decode(errors="replace")


def _kind_of(path: Path) -> files.EntryKind:
    if path.is_symlink():
        return files.EntryKind.SYMLINK
    if path.is_dir():
        return files.EntryKind.DIRECTORY
    if path.is_file():
        return files.EntryKind.REGULAR
    return files.EntryKind.OTHER

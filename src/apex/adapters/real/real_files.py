"""Atomic writes that leave nothing behind and never widen a mode."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from apex.kernel import bounded, claims, errors, hashing, identifiers, quantities, safepaths


class LocalFiles:
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
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return hashing.digest_bytes(payload)

    def exists(self, path: safepaths.SafePath) -> bool:
        return path.path.exists()

    def mode_of(self, path: safepaths.SafePath) -> quantities.FileMode:
        return quantities.FileMode(path.path.stat().st_mode & 0o777)

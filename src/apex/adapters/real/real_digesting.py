"""Stream a file once, and remember the answer against its stat key.

The key is the device, inode, size and modification time, never the path, so renaming a file
cannot serve a stale answer. A cold cache produces the same result, which is the property
that keeps this an optimisation.
"""

from __future__ import annotations

from apex.kernel import claims, errors, hashing, identifiers, safepaths
from apex.ports import digesting


class CachedDigests(digesting.DigestPort):
    environment = claims.EnvironmentKind.BUILD

    def __init__(self) -> None:
        self._cache: dict[hashing.StatKey, identifiers.Digest] = {}
        self.reads = 0

    def file(self, path: safepaths.SafePath) -> identifiers.Digest:
        try:
            key = hashing.StatKey.of(path.path)
        except OSError as error:
            raise errors.PortFailure(port="digesting", cause=str(error)) from error
        remembered = self._cache.get(key)
        if remembered is not None:
            return remembered
        self.reads += 1
        with path.path.open("rb") as handle:
            digest = hashing.digest_stream(iter(lambda: handle.read(hashing.READ_CHUNK), b""))
        self._cache[key] = digest
        return digest

    def forget(self) -> None:
        self._cache.clear()

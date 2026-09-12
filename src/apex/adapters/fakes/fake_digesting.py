"""The same caching behaviour over an in-memory count of reads."""

from __future__ import annotations

from apex.kernel import claims, errors, hashing, identifiers, safepaths
from apex.ports import digesting


class CountingDigests(digesting.DigestPort):
    environment = claims.EnvironmentKind.SIMULATED

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
        digest = hashing.digest_bytes(path.path.read_bytes())
        self._cache[key] = digest
        return digest

    def forget(self) -> None:
        self._cache.clear()

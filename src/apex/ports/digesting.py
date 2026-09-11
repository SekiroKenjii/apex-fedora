"""Hashing files, with a cache keyed on the file rather than on its name."""

from __future__ import annotations

from typing import Protocol

from apex.kernel import claims, identifiers, safepaths


class DigestPort(Protocol):
    environment: claims.EnvironmentKind

    def file(self, path: safepaths.SafePath) -> identifiers.Digest: ...

    def forget(self) -> None: ...

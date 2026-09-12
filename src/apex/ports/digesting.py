"""Hashing files, with a cache keyed on the file rather than on its name."""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from apex.kernel import claims, identifiers, safepaths


class DigestPort(Protocol):
    environment: claims.EnvironmentKind

    @abstractmethod
    def file(self, path: safepaths.SafePath) -> identifiers.Digest: ...

    @abstractmethod
    def forget(self) -> None: ...

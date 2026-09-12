"""Signing bytes and verifying a signature over bytes.

Verification takes the payload as bytes rather than as a path, so the document a caller
parses is exactly the document whose signature was checked. There is no second read for a
swap to slip between.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Protocol

from apex.kernel import claims, safepaths


class SigningPort(Protocol):
    environment: claims.EnvironmentKind

    @abstractmethod
    def verify(
        self, *, payload: bytes, signature: bytes, public_key: safepaths.RegularFile
    ) -> bool: ...

    @abstractmethod
    def sign(self, *, payload: bytes, private_key: safepaths.RegularFile) -> bytes: ...

    @abstractmethod
    def generate_key_pair(
        self, *, private_into: safepaths.SafePath, public_into: safepaths.SafePath
    ) -> None: ...

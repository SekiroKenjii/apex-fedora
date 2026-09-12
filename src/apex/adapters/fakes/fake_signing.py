"""Signatures without cryptography, holding the same contract.

A key pair is a shared secret written under two names. A signature is a keyed hash of the
payload, so a changed payload, another key or garbage all fail to verify, exactly as the real
adapter refuses them, and nothing here can be mistaken for a real signature.
"""

from __future__ import annotations

import hashlib
import hmac

from apex.adapters import parts
from apex.kernel import claims, errors, safepaths
from apex.ports import signing

PRIVATE_PREFIX = "private:"
PUBLIC_PREFIX = "public:"


class FakeSigner(signing.SigningPort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self) -> None:
        self._issued = 0

    def generate_key_pair(
        self, *, private_into: safepaths.SafePath, public_into: safepaths.SafePath
    ) -> None:
        self._issued += 1
        secret = f"key-{self._issued}"
        private_into.path.parent.mkdir(parents=True, exist_ok=True, mode=parts.PRIVATE_DIRECTORY)
        private_into.path.write_text(f"{PRIVATE_PREFIX}{secret}")
        private_into.path.chmod(parts.PRIVATE_FILE.value)
        public_into.path.write_text(f"{PUBLIC_PREFIX}{secret}")

    def sign(self, *, payload: bytes, private_key: safepaths.RegularFile) -> bytes:
        return _tag(_secret(private_key, PRIVATE_PREFIX), payload)

    def verify(
        self, *, payload: bytes, signature: bytes, public_key: safepaths.RegularFile
    ) -> bool:
        expected = _tag(_secret(public_key, PUBLIC_PREFIX), payload)
        return hmac.compare_digest(expected, signature)


class RejectingSigner(FakeSigner):
    """Every verification fails, so a caller's rejection path can be exercised."""

    def verify(
        self,
        *,
        payload: bytes,  # noqa: ARG002
        signature: bytes,  # noqa: ARG002
        public_key: safepaths.RegularFile,
    ) -> bool:
        _secret(public_key, PUBLIC_PREFIX)
        return False


def _secret(key: safepaths.RegularFile, prefix: str) -> str:
    if not key.path.is_file():
        raise errors.PortFailure(port="signing", cause=f"{key}: no such key")
    text = key.path.read_text()
    if not text.startswith(prefix):
        raise errors.PortFailure(port="signing", cause=f"{key}: not a {prefix[:-1]} key")
    return text[len(prefix):]


def _tag(secret: str, payload: bytes) -> bytes:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest().encode()


class AcceptingSigner(FakeSigner):
    """Every verification succeeds. Exists so the exercise can be shown to catch a verifier
    that accepts what it should refuse."""

    def verify(
        self,
        *,
        payload: bytes,  # noqa: ARG002
        signature: bytes,  # noqa: ARG002
        public_key: safepaths.RegularFile,
    ) -> bool:
        _secret(public_key, PUBLIC_PREFIX)
        return True

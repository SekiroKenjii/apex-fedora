"""Ed25519 signatures through the openssl command."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from apex.adapters import parts
from apex.config import defaults
from apex.kernel import claims, errors, safepaths
from apex.ports import signing

PROGRAM = "openssl"
ALGORITHM = "ED25519"
REJECTED = 1


def _run(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(  # noqa: S603
            [PROGRAM, *arguments],
            capture_output=True,
            timeout=defaults.SIGNING_DEADLINE.budget.seconds,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as fault:
        raise errors.PortFailure(port="signing", cause=str(fault)) from fault


def _succeed(arguments: list[str]) -> bytes:
    completed = _run(arguments)
    if completed.returncode:
        raise errors.PortFailure(port="signing", cause=completed.stderr.decode(errors="replace"))
    return completed.stdout


class OpensslSigner(signing.SigningPort):
    environment = claims.EnvironmentKind.BUILD

    def generate_key_pair(
        self, *, private_into: safepaths.SafePath, public_into: safepaths.SafePath
    ) -> None:
        private_into.path.parent.mkdir(parents=True, exist_ok=True, mode=parts.PRIVATE_DIRECTORY)
        _succeed(["genpkey", "-algorithm", ALGORITHM, "-out", str(private_into)])
        private_into.path.chmod(parts.PRIVATE_FILE.value)
        _succeed(["pkey", "-in", str(private_into), "-pubout", "-out", str(public_into)])

    def sign(self, *, payload: bytes, private_key: safepaths.RegularFile) -> bytes:
        with tempfile.TemporaryDirectory() as scratch:
            document = Path(scratch) / "payload"
            signature = Path(scratch) / "signature"
            document.write_bytes(payload)
            _succeed(
                [
                    "pkeyutl",
                    "-sign",
                    "-rawin",
                    "-inkey",
                    str(private_key),
                    "-in",
                    str(document),
                    "-out",
                    str(signature),
                ]
            )
            return signature.read_bytes()

    def verify(
        self, *, payload: bytes, signature: bytes, public_key: safepaths.RegularFile
    ) -> bool:
        if not public_key.path.is_file():
            raise errors.PortFailure(port="signing", cause=f"{public_key}: no such key")
        with tempfile.TemporaryDirectory() as scratch:
            document = Path(scratch) / "payload"
            sigfile = Path(scratch) / "signature"
            document.write_bytes(payload)
            sigfile.write_bytes(signature)
            completed = _run(
                [
                    "pkeyutl",
                    "-verify",
                    "-rawin",
                    "-pubin",
                    "-inkey",
                    str(public_key),
                    "-in",
                    str(document),
                    "-sigfile",
                    str(sigfile),
                ]
            )
        if completed.returncode == 0:
            return True
        if completed.returncode == REJECTED:
            return False
        raise errors.PortFailure(port="signing", cause=completed.stderr.decode(errors="replace"))

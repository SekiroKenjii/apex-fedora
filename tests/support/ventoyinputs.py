"""Every input the Ventoy medium needs, small, under a runtime root, agreeing with a lock.

The live bundle is signed with the fake signer over a nested ISO; the Ubuntu image is a few
bytes whose digest the synthetic lock pins; the checksums name it; a scripted `gpgv` says the
pinned signer signed them; the Ventoy release and its checksum file are served offline.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

from apex.adapters.fakes import fake_downloading, fake_process
from apex.config import defaults
from apex.kernel import commands, hashing, safepaths
from apex.model import bundles
from apex.ports import portset
from apex.provisioning.fixtures import ventoy_fixture

VERSION = "1.1.17"
COMMIT = "7cbdc5cf69935bcf1f085ae67f40e70ea7e74bae"
SIGNER = "843938DF228D22F7B3742BC0D94AA3F0EFE21092"
ARCHIVE_URL = (
    f"https://github.com/ventoy/Ventoy/releases/download/v{VERSION}/ventoy-{VERSION}-linux.tar.gz"
)
SUMS_URL = f"https://github.com/ventoy/Ventoy/releases/download/v{VERSION}/sha256.txt"
UBUNTU_NAME = "ubuntu-26.04-desktop-amd64.iso"
ARCHIVE = b"the ventoy release archive"
LIVE_ISO = b"the signed live medium"
UBUNTU_ISO = b"the ubuntu image"
MEDIUM = b"the prepared medium as qcow2"
SIGNED_DIGEST = "sha256:" + "a" * 64


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sums_text() -> bytes:
    return f"{digest(ARCHIVE)}  ventoy-{VERSION}-linux.tar.gz\n".encode()


def lock_document() -> dict[str, Any]:
    return {
        "schema": 1,
        "ventoy": {
            "version": VERSION,
            "commit": COMMIT,
            "url": ARCHIVE_URL,
            "sha256": digest(ARCHIVE),
            "checksum_url": SUMS_URL,
            "checksum_sha256": digest(sums_text()),
        },
        "ubuntu": {
            "filename": UBUNTU_NAME,
            "url": f"https://releases.ubuntu.com/26.04/{UBUNTU_NAME}",
            "sha256": digest(UBUNTU_ISO),
            "bytes": len(UBUNTU_ISO),
            "signer": SIGNER,
        },
    }


def write_lock(repository: Path) -> None:
    target = repository / defaults.VENTOY_LOCK_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(lock_document(), indent=2) + "\n")


@dataclasses.dataclass(frozen=True, slots=True)
class Laid:
    live_output: Path
    ubuntu: Path
    trusted_key: Path
    checksums: Path
    signature: Path
    keyring: Path


def lay_out(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, private: Path, public: Path
) -> Laid:
    """The signed live output with its nested ISO, and the Ubuntu inputs beside the root."""
    output = root.path / "exports" / ("f" * 32) / "output"
    (output / "live").mkdir(parents=True)
    (output / "live" / "Apex-Live.iso").write_bytes(LIVE_ISO)
    files = {
        str(path.relative_to(output)): hashing.digest_bytes(path.read_bytes()).hex
        for path in sorted(output.rglob("*"))
        if path.is_file()
    }
    inventory = json.dumps({"schema": 1, "digest": SIGNED_DIGEST, "files": files}).encode()
    (output / bundles.MANIFEST_NAME).write_bytes(inventory)
    (output / bundles.SIGNATURE_NAME).write_bytes(
        ports.signing.sign(payload=inventory, private_key=safepaths.RegularFile.adopt(private))
    )
    ubuntu = root.path / "inputs" / UBUNTU_NAME
    ubuntu.parent.mkdir()
    ubuntu.write_bytes(UBUNTU_ISO)
    beside = root.path.parent / "ubuntu"
    beside.mkdir()
    (beside / "SHA256SUMS").write_bytes(f"{digest(UBUNTU_ISO)} *{UBUNTU_NAME}\n".encode())
    (beside / "SHA256SUMS.gpg").write_bytes(b"a detached signature")
    (beside / "keyring.gpg").write_bytes(b"a keyring")
    return Laid(
        live_output=output,
        ubuntu=ubuntu,
        trusted_key=public,
        checksums=beside / "SHA256SUMS",
        signature=beside / "SHA256SUMS.gpg",
        keyring=beside / "keyring.gpg",
    )


class Gpgv(fake_process.ScriptedProcess):
    """Answers every gpgv run with a valid signature by one signer, and records the argv."""

    def __init__(self, signer: str = SIGNER, *, exit_code: int = 0) -> None:
        super().__init__()
        self.signer = signer
        self.exit_code = exit_code
        self.gpgv: list[list[str]] = []

    def run(self, argv: commands.Argv, **keywords: Any) -> commands.CompletedRun:
        if argv.arguments[0] != "gpgv":
            return super().run(argv, **keywords)
        self.gpgv.append(list(argv))
        status = f"[GNUPG:] NEWSIG\n[GNUPG:] VALIDSIG {self.signer} 2026-04-23 0 4 0 1 10 01 X\n"
        return commands.CompletedRun(
            exit_code=self.exit_code, stdout=status.encode(), stderr=b"", truncated=False
        )


def fetcher() -> fake_downloading.OfflineFetcher:
    return fake_downloading.OfflineFetcher({ARCHIVE_URL: ARCHIVE, SUMS_URL: sums_text()})


def report(request_files: dict[str, str]) -> dict[str, Any]:
    return {
        "status": "PASS",
        "request": {"files": request_files, "ventoy_version": VERSION},
        "partition_table": {},
        "ventoy_info": f"{ventoy_fixture.VERSION_LINE}{VERSION}",
        "image_sha256": digest(MEDIUM),
        "physical_media_accessed": False,
        "boot_acceptance": "NOT TESTED",
    }


def request_files() -> dict[str, str]:
    return {
        ventoy_fixture.ARCHIVE: digest(ARCHIVE),
        ventoy_fixture.ISOS[0]: digest(LIVE_ISO),
        ventoy_fixture.ISOS[1]: digest(UBUNTU_ISO),
    }

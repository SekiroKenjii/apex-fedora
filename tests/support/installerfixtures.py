"""An offline installer guest at its diagnostic target, as the payload fault expects it.

One spec names the guest's state and what the entry point does when run; the fake tree and
the fake programs are derived from it, and the older script's directories on disk can be
derived from the same spec, so a mutation reaches both sides of a parity.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
from typing import Any

from apex.adapters.fakes import (
    fake_archives,
    fake_blockdevices,
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_extents,
    fake_files,
    fake_ids,
    fake_process,
)
from apex.agent import agentports
from apex.config import defaults
from apex.kernel import quantities, safepaths

PUBLIC = quantities.FileMode(0o444)
BLOB = b'{"test-config":true}'
BLOB_DIGEST = hashlib.sha256(BLOB).hexdigest()
MANIFEST = json.dumps({"config": {"digest": "sha256:" + BLOB_DIGEST}}).encode()
SIGNATURE = b"synthetic signature"
ORIGINAL_KEY = b"original public fixture"
WRONG_KEY = "-----BEGIN PUBLIC KEY-----\nsynthetic fixture\n"
PAYLOAD_DIGEST = "sha256:" + "a" * 64
METADATA = {
    "digest": PAYLOAD_DIGEST,
    "image_id": "sha256:" + BLOB_DIGEST,
    "purpose": "development-installer-only",
    "reference": "localhost/apex-payload@" + PAYLOAD_DIGEST,
    "identity": "localhost/apex-payload:" + "a" * 64,
    "public_key_sha256": hashlib.sha256(ORIGINAL_KEY).hexdigest(),
}
ERRORS = {
    "missing-signature": "no signature found",
    "altered-signature": "invalid signature",
    "wrong-key": "signature rejected by key",
    "changed-manifest": "Bundled manifest digest changed",
    "corrupt-blob": "Bundled blob checksum mismatch: sha256:" + BLOB_DIGEST,
    "unexpected-source": "Unexpected payload source",
}
DISKS = {
    "blockdevices": [
        {
            "name": "vda",
            "size": 48 * 1024**3,
            "type": "disk",
            "serial": "target",
            "mountpoints": [None],
        },
        {
            "name": "vdb",
            "size": 4 * 1024**3,
            "type": "disk",
            "serial": "apex-other-1",
            "mountpoints": [None],
            "children": [{"name": "vdb1", "mountpoints": [None]}],
        },
        {"name": "zram0", "size": 1024**3, "type": "disk", "mountpoints": ["[SWAP]"]},
    ]
}


@dataclasses.dataclass(frozen=True, slots=True)
class InstallerSpec:
    cmdline: str = "BOOT_IMAGE=/vmlinuz systemd.unit=multi-user.target"
    enforcement: str = "Enforcing"
    interfaces: tuple[str, ...] = ("lo",)
    disks: dict[str, Any] = dataclasses.field(default_factory=lambda: dict(DISKS))
    anaconda_state: str = "ActiveState=inactive\nExecMainStartTimestampMonotonic=0"
    anaconda_running: bool = False
    entered: bool = False
    signatures: tuple[str, ...] = ("signature-1",)
    entry_exit: int = 1
    preflight_status: str = "FAIL"
    preflight_error: str | None = None
    creates_log: bool = False
    enforcement_after: str = "Enforcing"

    def files(self) -> dict[str, bytes]:
        payload = defaults.INSTALLER_PAYLOAD
        trust = defaults.INSTALLER_TRUST
        found = {
            "/proc/cmdline": f"{self.cmdline}\n".encode(),
            f"{payload}/manifest.json": MANIFEST,
            f"{payload}/{BLOB_DIGEST}": BLOB,
            f"{trust}/payload.pub": ORIGINAL_KEY,
            f"{trust}/payload.json": json.dumps(METADATA).encode(),
            defaults.INSTALLER_MARKER: json.dumps({"reference": METADATA["reference"]}).encode(),
            defaults.CONTAINER_POLICY: json.dumps({"default": [{"type": "reject"}]}).encode(),
            "/proc/1/comm": b"systemd\n",
            "/proc/2/comm": b"anaconda\n" if self.anaconda_running else b"bash\n",
        }
        for name in self.signatures:
            found[f"{payload}/{name}"] = SIGNATURE
        if self.entered:
            found[defaults.INSTALLER_PREFLIGHT_RECORD] = b"{}"
        return found


class Installer(fake_process.ScriptedProcess):
    """Answers the guest's programs and does what the entry point leaves behind."""

    def __init__(self, spec: InstallerSpec, files: fake_files.MemoryFiles, case: str) -> None:
        super().__init__()
        self.spec = spec
        self.files = files
        self.case = case
        self.entered = False

    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        self.expect(vector, self._answer(vector))
        return super().run(argv, **keywords)

    def _answer(self, vector: tuple[str, ...]) -> fake_process.Reply:
        spec = self.spec
        if vector == ("systemd-detect-virt", "--vm"):
            return fake_process.Reply(stdout=b"kvm\n")
        if vector == ("getenforce",):
            state = spec.enforcement_after if self.entered else spec.enforcement
            return fake_process.Reply(stdout=f"{state}\n".encode())
        if vector[:3] == ("systemctl", "show", "anaconda.service"):
            return fake_process.Reply(stdout=f"{spec.anaconda_state}\n".encode())
        if vector[:1] == ("lsblk",):
            return fake_process.Reply(stdout=json.dumps(spec.disks).encode())
        if vector == ("/usr/bin/anaconda", "--text"):
            self.entered = True
            error = spec.preflight_error if spec.preflight_error is not None else ERRORS[self.case]
            record = {"status": spec.preflight_status, "error": error}
            self.files.write_atomic(
                safepaths.SafePath(Path(defaults.INSTALLER_PREFLIGHT_RECORD)),
                json.dumps(record).encode(),
                mode=PUBLIC,
            )
            if spec.creates_log:
                self.files.write_atomic(
                    safepaths.SafePath(Path(defaults.ANACONDA_LOG)), b"log\n", mode=PUBLIC
                )
            return fake_process.Reply(
                exit_code=spec.entry_exit, stderr=b"Apex: installation blocked before Anaconda\n"
            )
        return fake_process.Reply()


def installer_guest(
    spec: InstallerSpec, case: str = "missing-signature"
) -> tuple[Installer, fake_files.MemoryFiles, agentports.AgentPorts]:
    files = fake_files.MemoryFiles()
    for name, content in spec.files().items():
        files.write_atomic(safepaths.SafePath(Path(name)), content, mode=PUBLIC)
    for interface in spec.interfaces:
        files.make_directory(safepaths.SafePath(Path("/sys/class/net") / interface), mode=PUBLIC)
    process = Installer(spec, files, case)
    ports = agentports.AgentPorts(
        processes=process,
        files=files,
        clock=fake_clock.ManualClock(),
        containers=fake_containers.FakeRegistry(),
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(),
        blocks=fake_blockdevices.FakeBlockDevices(),
    )
    return process, files, ports


def older_tree(spec: InstallerSpec, base: Path) -> Path:
    """The payload and trust directories on disk, rooted under `base`, for the older script."""
    for name, content in spec.files().items():
        target = base / name.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    (base / defaults.INSTALLER_FAULT_DIRECTORY.lstrip("/")).parent.mkdir(
        parents=True, exist_ok=True
    )
    return base

"""A build's signed output under a runtime root, made with the fake signer on real files."""

from __future__ import annotations

import json
from pathlib import Path

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_downloading,
    fake_guestshell,
    fake_hypervisor,
    fake_ids,
    fake_locking,
    fake_process,
    fake_qmp,
    fake_signing,
)
from apex.adapters.real import real_digesting, real_files
from apex.kernel import hashing, identifiers, safepaths
from apex.model import bundles
from apex.ports import portset

BUILD = identifiers.BuildId("e" * 32)
SIGNED_DIGEST = "sha256:" + "a" * 64


def real_files_bundle() -> portset.HostPorts:
    """Fakes everywhere but the files and digests, which the signed bundle needs on disk."""
    return portset.HostPorts(
        processes=fake_process.ScriptedProcess(),
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        identities=fake_ids.SequenceIdentities(),
        locks=fake_locking.MemoryLocks(),
        digests=real_digesting.CachedDigests(),
        archives=fake_archives.MemoryArchives(),
        signing=fake_signing.FakeSigner(),
        downloads=fake_downloading.OfflineFetcher({}),
        hypervisor=fake_hypervisor.FakeQemu(),
        monitor=fake_qmp.ScriptedQmp({"system_powerdown": {}}),
        guest=fake_guestshell.ScriptedGuest(),
    )


def keys(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> tuple[Path, Path]:
    """A signing pair under the root's keys directory: the private path and the public path."""
    ports.signing.generate_key_pair(
        private_into=root.child("keys/signing.key"), public_into=root.child("keys/trusted.pub")
    )
    return root.path / "keys" / "signing.key", root.path / "keys" / "trusted.pub"


def signed_output(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    private: Path,
    *,
    build: identifiers.BuildId = BUILD,
    digest: str = SIGNED_DIGEST,
    extra: dict[str, bytes] | None = None,
) -> Path:
    """The build's output directory with a payload, an inventory and its signature."""
    directory = root.path / "exports" / str(build) / "output"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "payload.txt").write_bytes(b"frozen artifact")
    for name, body in (extra or {}).items():
        (directory / name).write_bytes(body)
    files = {
        path.name: hashing.digest_bytes(path.read_bytes()).hex
        for path in sorted(directory.iterdir())
        if path.name not in (bundles.MANIFEST_NAME, bundles.SIGNATURE_NAME)
    }
    inventory = json.dumps({"schema": 1, "digest": digest, "files": files}).encode()
    (directory / bundles.MANIFEST_NAME).write_bytes(inventory)
    (directory / bundles.SIGNATURE_NAME).write_bytes(
        ports.signing.sign(payload=inventory, private_key=safepaths.RegularFile.adopt(private))
    )
    return directory

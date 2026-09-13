"""An installed test guest as the recovery probes expect it, built from one spec.

The spec names the deployment digests, the GRUB fragments and the retry configuration; the
fake tree and the fake programs are both derived from it.
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
from apex.agent import agentports, grubstatic
from apex.config import defaults
from apex.kernel import quantities, safepaths

PUBLIC = quantities.FileMode(0o444)
BOOTED = "sha256:" + "a" * 64
ROLLBACK = "sha256:" + "b" * 64
PRESET = b"GREENBOOT_MAX_BOOT_ATTEMPTS=1\n"
PRE = b"pre\n"
STATIC = "/usr/lib/bootupd/grub2-static"
CONFIGURATIONS = ("/etc/greenboot/greenboot.conf", "/usr/share/apex/greenboot.conf")


@dataclasses.dataclass(frozen=True, slots=True)
class InstalledSpec:
    booted: str = BOOTED
    rollback: str | None = ROLLBACK
    fragment: bytes = grubstatic.SEPARATOR
    grub_suffix: bytes = b""
    system_preset: bytes = PRESET
    image_preset: bytes = PRESET
    enforcement: str = "Enforcing"
    virtualiser: str = "kvm"
    ostree: bool = True

    @property
    def fragments(self) -> dict[str, bytes]:
        return {grubstatic.GREENBOOT_FRAGMENT: self.fragment}

    @property
    def grub(self) -> bytes:
        return grubstatic.assemble(PRE, self.fragments) + self.grub_suffix

    @property
    def status(self) -> dict[str, object]:
        rollback = None if self.rollback is None else {"image": {"imageDigest": self.rollback}}
        return {"status": {"booted": {"image": {"imageDigest": self.booted}}, "rollback": rollback}}

    @property
    def files(self) -> dict[str, bytes]:
        found = {
            defaults.BOOT_ID: b"test-boot\n",
            f"{STATIC}/grub-static-pre.cfg": PRE,
            f"{STATIC}/configs.d/{grubstatic.GREENBOOT_FRAGMENT}": self.fragment,
            "/boot/grub2/grub.cfg": self.grub,
            CONFIGURATIONS[0]: self.system_preset,
            CONFIGURATIONS[1]: self.image_preset,
            "/usr/lib/greenboot/check/required.d/20-apex-system.sh": b"#!/bin/sh\n",
        }
        if self.ostree:
            found[defaults.OSTREE_BOOTED] = b""
        return found

    @property
    def outputs(self) -> dict[tuple[str, ...], bytes]:
        return {
            ("systemd-detect-virt", "--vm"): f"{self.virtualiser}\n".encode(),
            ("bootc", "status", "--format", "json"): json.dumps(self.status).encode(),
            ("getenforce",): f"{self.enforcement}\n".encode(),
            ("rpm", "-q", "bootupd", "greenboot", "bootc"): b"test versions\n",
            ("grub2-editenv", "-", "list"): b"boot_success=1\n",
        }


def config_digest(spec: InstalledSpec) -> str:
    return hashlib.sha256(spec.system_preset).hexdigest()


class Answering(fake_process.ScriptedProcess):
    """Answers the spec's programs and records the rest with an empty reply."""

    def __init__(self, spec: InstalledSpec) -> None:
        super().__init__()
        self.outputs = spec.outputs
        self.failing: set[tuple[str, ...]] = set()

    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        exit_code = 1 if vector in self.failing else 0
        self.expect(
            vector, fake_process.Reply(exit_code=exit_code, stdout=self.outputs.get(vector, b""))
        )
        return super().run(argv, **keywords)


def installed_guest(spec: InstalledSpec) -> tuple[Answering, agentports.AgentPorts]:
    files = fake_files.MemoryFiles()
    for name, content in spec.files.items():
        files.write_atomic(safepaths.SafePath(Path(name)), content, mode=PUBLIC)
    process = Answering(spec)
    ports = agentports.AgentPorts(
        processes=process, files=files, clock=fake_clock.ManualClock(),
        containers=fake_containers.FakeRegistry(), digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(), identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(), blocks=fake_blockdevices.FakeBlockDevices(),
    )
    return process, ports

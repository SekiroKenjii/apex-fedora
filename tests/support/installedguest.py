"""An installed guest for the operation units: a tree, a program table, root and a namespace."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memorydigests import MemoryDigests

from apex.adapters.fakes import (
    fake_archives,
    fake_blockdevices,
    fake_clock,
    fake_containers,
    fake_extents,
    fake_files,
    fake_ids,
    fake_process,
)
from apex.agent import agentports
from apex.config import defaults
from apex.kernel import quantities, safepaths

PUBLIC = quantities.FileMode(0o644)
COMPONENTS = b"bootupd=0.2.35\ngreenboot=0.16.4\n"


class Replying(fake_process.ScriptedProcess):
    """Answers from a table of argument vectors; a vector not in it succeeds with nothing."""

    def __init__(self, outputs: dict[tuple[str, ...], bytes]) -> None:
        super().__init__()
        self.outputs = dict(outputs)
        self.failing: set[tuple[str, ...]] = set()

    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        self.expect(
            vector,
            fake_process.Reply(
                exit_code=1 if vector in self.failing else 0,
                stdout=self.outputs.get(vector, b""),
                stderr=b"failed\n" if vector in self.failing else b"",
            ),
        )
        return super().run(argv, **keywords)

    def vectors(self) -> list[tuple[str, ...]]:
        return [tuple(call) for call in self.calls]


def bootc_status(
    booted: str,
    *,
    rollback: str | None,
    staged: str | None = None,
    queued: bool = False,
    checksums: tuple[str, str] = ("1" * 64, "2" * 64),
) -> bytes:
    def deployment(image: str | None, checksum: str) -> dict[str, Any] | None:
        if image is None:
            return None
        return {
            "image": {"imageDigest": image},
            "ostree": {"checksum": checksum, "stateroot": "fedora", "deploySerial": 0},
        }

    return json.dumps(
        {
            "status": {
                "booted": deployment(booted, checksums[0]),
                "rollback": deployment(rollback, checksums[1]),
                "staged": deployment(staged, "3" * 64),
                "rollbackQueued": queued,
            }
        }
    ).encode()


def guest(
    tree: dict[str, bytes],
    outputs: dict[tuple[str, ...], bytes],
    *,
    links: dict[str, str] | None = None,
    directories: tuple[str, ...] = (),
) -> tuple[Replying, fake_files.MemoryFiles, agentports.AgentPorts]:
    files = fake_files.MemoryFiles()
    files.write_atomic(safepaths.SafePath(Path(defaults.OSTREE_BOOTED)), b"", mode=PUBLIC)
    files.write_atomic(safepaths.SafePath(Path(defaults.BOOT_ID)), b"boot-1\n", mode=PUBLIC)
    for name, content in tree.items():
        files.write_atomic(safepaths.SafePath(Path(name)), content, mode=PUBLIC)
    for source, target in (links or {}).items():
        files.symlink(safepaths.SafePath(Path(source)), target=safepaths.SafePath(Path(target)))
    for name in directories:
        files.directories.add(name)
    process = Replying({("systemd-detect-virt", "--vm"): b"kvm\n", **outputs})
    ports = agentports.AgentPorts(
        processes=process,
        files=files,
        clock=fake_clock.ManualClock(),
        containers=fake_containers.FakeRegistry(),
        digests=MemoryDigests(files),
        archives=fake_archives.MemoryArchives(filesystem=files),
        identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(),
        blocks=fake_blockdevices.FakeBlockDevices(),
    )
    return process, files, ports

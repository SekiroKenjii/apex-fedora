"""A live guest stopped at its pre-mount breakpoint, with a kernel that answers the lock fault.

The process fake moves the tree the way the guest would: making the sentinel writable
clears its read-only flag, the guard's denied lock sets the latch, restoring sets the flag
again. What it answers for the restricted child is the test's to choose.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from livefixture_trees import GUARD_TEXT, Guest, guest, virtio_fixture

from apex.adapters.fakes import fake_files, fake_process
from apex.agent import blockdevices
from apex.config import defaults
from apex.kernel import commands, quantities, safepaths

DIGEST = hashlib.sha256(GUARD_TEXT).hexdigest()
PUBLIC = quantities.FileMode(0o444)
LATCH = safepaths.SafePath(Path(defaults.PROTECTION_LATCH))
CAPS_WITHOUT_ADMIN = b"CapEff:\t000001ffffdfffff\nCapBnd:\t000001ffffdfffff\n"
CAPS_WITH_ADMIN = b"CapEff:\t000001ffffffffff\nCapBnd:\t000001ffffdfffff\n"
DENIAL = b"blockdev: ioctl error on BLKROSET: Permission denied\n"
DETECT = ("systemd-detect-virt", "--vm")


class Kernel(fake_process.ScriptedProcess):
    def __init__(
        self,
        files: fake_files.MemoryFiles,
        *,
        caps: bytes = CAPS_WITHOUT_ADMIN,
        denial: bytes = DENIAL,
        guard_exit: int = 1,
        restores: bool = True,
        latches: bool = True,
    ) -> None:
        super().__init__()
        self.files = files
        self.caps = caps
        self.denial = denial
        self.guard_exit = guard_exit
        self.restores = restores
        self.latches = latches
        self.expect(DETECT, fake_process.Reply(stdout=b"kvm\n"))

    def run(self, argv: commands.Argv, **keywords: Any) -> commands.CompletedRun:
        vector = list(argv)
        if tuple(vector) != DETECT:
            self.expect(tuple(vector), self._answer(vector))
        return super().run(argv, **keywords)

    def _answer(self, vector: list[str]) -> fake_process.Reply:
        if vector[:2] == ["blockdev", "--setrw"]:
            self.read_only(vector[2], b"0\n")
        elif vector[:2] == ["blockdev", "--setro"]:
            self.read_only(vector[2], b"1\n" if self.restores else b"0\n")
        elif vector[:2] == ["/bin/sh", "-c"]:
            if self.latches:
                self.files.write_atomic(LATCH, b"", mode=PUBLIC)
            return fake_process.Reply(
                exit_code=self.guard_exit, stdout=self.caps, stderr=self.denial
            )
        return fake_process.Reply()

    def read_only(self, device: str, value: bytes) -> None:
        name = device.removeprefix("/dev/")
        home = self.files.resolve(blockdevices.SYSFS_BLOCK / name)
        self.files.write_atomic(home / "ro", value, mode=PUBLIC)


def breakpoint_guest(**keywords: Any) -> Guest:
    files = fake_files.MemoryFiles()
    fixture = guest(virtio_fixture(), initramfs=True, files=files)
    fixture.process = Kernel(files, **keywords)
    return fixture

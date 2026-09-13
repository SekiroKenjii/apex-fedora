"""A laptop and an installer guest as the diagnostics collectors expect them."""

from __future__ import annotations

from pathlib import Path

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
DESTINATION = "/run/media/operator/usb/apex-diagnostics.json"
CODECS = {
    "/proc/asound/card0/codec#0": b"Codec: Realtek ALC294\n",
    "/proc/asound/card1/codec#2": b"Codec: HDMI\n",
}


def bundle(
    process: fake_process.ScriptedProcess, files: fake_files.MemoryFiles
) -> agentports.AgentPorts:
    return agentports.AgentPorts(
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


def answering(*argvs: tuple[str, ...]) -> fake_process.ScriptedProcess:
    process = fake_process.ScriptedProcess()
    process.expect(("systemd-detect-virt", "--vm"), fake_process.Reply(stdout=b"kvm\n"))
    for argv in argvs:
        process.expect(argv, fake_process.Reply(stdout=b"observed\n"))
    return process


def laptop() -> fake_files.MemoryFiles:
    files = fake_files.MemoryFiles()
    asound = safepaths.SafePath(Path("/proc/asound"))
    for name, text in CODECS.items():
        files.write_atomic(safepaths.SafePath(Path(name)), text, mode=PUBLIC)
    files.write_atomic(asound / "card0" / "id", b"PCH\n", mode=PUBLIC)
    files.write_atomic(asound / "cards", b" 0 [PCH]\n", mode=PUBLIC)
    return files


def installer() -> fake_files.MemoryFiles:
    files = fake_files.MemoryFiles()
    files.write_atomic(
        safepaths.SafePath(Path(defaults.INSTALLER_MARKER)),
        b'{"reference": "localhost/apex-payload:' + b"b" * 64 + b'"}',
        mode=PUBLIC,
    )
    files.write_atomic(safepaths.SafePath(Path(defaults.BOOT_ID)), b"fixture-boot\n", mode=PUBLIC)
    files.write_atomic(
        safepaths.SafePath(Path("/tmp/anaconda.log")), b"anaconda started\n", mode=PUBLIC
    )
    files.write_atomic(
        safepaths.SafePath(Path("/run/apex/installer-preflight.json")),
        b'{"status": "FAIL"}',
        mode=PUBLIC,
    )
    return files

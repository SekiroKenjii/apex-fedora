"""The two observation probes read through ports and never declare a test passed."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

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
from apex.agent import agentports, guestguard
from apex.agent.units import live_observe_unit, ventoy_observe_unit
from apex.config import defaults
from apex.kernel import quantities, safepaths

SYSFS = safepaths.SafePath(Path("/sys/class/block"))
DEVICES = safepaths.SafePath(Path("/sys/devices/pci0000:00/0000:00:04.0/virtio1/block"))
PUBLIC = quantities.FileMode(0o444)
GUARD = "/usr/libexec/apex/live-disk-guard.sh"


def process(*answered: tuple[str, ...]) -> fake_process.ScriptedProcess:
    scripted = fake_process.ScriptedProcess()
    scripted.expect(("systemd-detect-virt", "--vm"), fake_process.Reply(stdout=b"kvm\n"))
    for argv in answered:
        scripted.expect(argv, fake_process.Reply(stdout=b"answer\n"))
    return scripted


def tree(*, live: bool) -> fake_files.MemoryFiles:
    files = fake_files.MemoryFiles()
    cmdline = f"BOOT_IMAGE=/vmlinuz {defaults.LIVE_ROOT_TOKEN}\n" if live else "root=/dev/vda3\n"
    files.write_atomic(safepaths.SafePath(Path("/proc/cmdline")), cmdline.encode(), mode=PUBLIC)
    files.write_atomic(safepaths.SafePath(Path("/proc/swaps")), b"Filename\n", mode=PUBLIC)
    files.write_atomic(safepaths.SafePath(Path("/etc/os-release")), b"ID=fedora\n", mode=PUBLIC)
    files.write_atomic(
        safepaths.SafePath(Path(GUARD)), b"#!/bin/sh\n", mode=quantities.FileMode(0o755)
    )
    files.labels[GUARD] = "system_u:object_r:bin_t:s0"
    files.write_atomic(
        safepaths.SafePath(Path("/usr/libexec/flatpak-system-helper")), b"\x7fELF", mode=PUBLIC
    )
    files.make_directory(SYSFS, mode=PUBLIC)
    for name, number, partition in (("vda", "253:0", None), ("vda1", "253:1", 1)):
        home = DEVICES / "vda" if partition is None else DEVICES / "vda" / name
        files.write_atomic(home / "dev", f"{number}\n".encode(), mode=PUBLIC)
        files.write_atomic(home / "ro", b"1\n", mode=PUBLIC)
        files.write_atomic(home / "size", b"8388608\n", mode=PUBLIC)
        if partition is not None:
            files.write_atomic(home / "partition", f"{partition}\n".encode(), mode=PUBLIC)
        else:
            files.write_atomic(home / "serial", b"apex-other-1\n", mode=PUBLIC)
            files.make_directory(home / "slaves", mode=PUBLIC)
        files.make_directory(home / "holders", mode=PUBLIC)
        files.symlink(SYSFS / name, target=home)
    return files


def bundle(
    scripted: fake_process.ScriptedProcess, files: fake_files.MemoryFiles
) -> agentports.AgentPorts:
    return agentports.AgentPorts(
        processes=scripted,
        files=files,
        clock=fake_clock.ManualClock(),
        containers=fake_containers.FakeRegistry(),
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(),
        blocks=fake_blockdevices.FakeBlockDevices(),
    )


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)


def test_the_live_probe_reports_every_older_section_and_claims_nothing() -> None:
    answered = tuple(tuple(argv) for argv in live_observe_unit.COMMANDS.values())
    scripted = process(*answered)

    report = live_observe_unit.run(bundle(scripted, tree(live=True)), arguments={})

    assert report["live_acceptance"] == "NOT TESTED"
    assert report["write_denial_test"] == "NOT TESTED"
    commands = report["commands"]
    assert isinstance(commands, dict) and set(commands) == set(live_observe_unit.COMMANDS)
    assert commands["kernel"] == {
        "argv": ["uname", "-r"],
        "returncode": 0,
        "stdout": "answer\n",
        "stderr": "",
        "truncated": False,
    }
    files = report["files"]
    assert isinstance(files, dict) and set(files) == set(live_observe_unit.FILES)
    assert files[GUARD] == {
        "text": "#!/bin/sh\n",
        "truncated": False,
        "sha256": hashlib.sha256(b"#!/bin/sh\n").hexdigest(),
    }
    absent = "/run/apex-disks-protected"
    assert files[absent] == {"error": f"{absent}: no such file"}
    metadata = report["executable_metadata"]
    assert isinstance(metadata, dict)
    assert metadata["/usr/libexec/flatpak-system-helper"] == {
        "uid": 0,
        "gid": 0,
        "mode": "0o444",
        "selinux": None,
    }
    absent_helper = metadata["/run/rootfsbase/usr/libexec/flatpak-system-helper"]
    assert isinstance(absent_helper, dict) and "error" in absent_helper
    blocks = report["block_devices"]
    assert isinstance(blocks, dict) and set(blocks) == {"vda", "vda1"}
    whole, part = blocks["vda"], blocks["vda1"]
    assert isinstance(whole, dict) and isinstance(part, dict)
    assert part["partition"] == 1 and whole["serial"] == "apex-other-1"


def test_the_live_probe_refuses_outside_the_live_medium_before_observing() -> None:
    scripted = process()

    with pytest.raises(Exception, match="probe.environment-unexpected"):
        live_observe_unit.run(bundle(scripted, tree(live=False)), arguments={})

    assert [tuple(call) for call in scripted.calls] == [("systemd-detect-virt", "--vm")]


def test_the_ventoy_probe_reports_topology_with_no_slaves_for_a_partition() -> None:
    answered = tuple(tuple(argv) for argv in ventoy_observe_unit.COMMANDS.values())
    scripted = process(*answered)

    report = ventoy_observe_unit.run(bundle(scripted, tree(live=False)), arguments={})

    commands = report["commands"]
    assert isinstance(commands, dict) and set(commands) == set(ventoy_observe_unit.COMMANDS)
    blocks = report["blocks"]
    assert isinstance(blocks, dict)
    assert blocks["vda"] == {"path": str(DEVICES / "vda"), "ro": "1", "dev": "253:0", "slaves": []}
    part = blocks["vda1"]
    assert isinstance(part, dict) and part["slaves"] is None
    files = report["files"]
    assert isinstance(files, dict) and set(files) == set(ventoy_observe_unit.FILES)
    release = files["/etc/os-release"]
    assert isinstance(release, dict) and release["text"] == "ID=fedora\n"
    assert "PASS" not in str(report)


def test_a_program_that_is_missing_is_recorded_as_an_observation() -> None:
    answered = tuple(tuple(argv) for argv in ventoy_observe_unit.COMMANDS.values())
    scripted = process(*answered)
    scripted.expect(("efibootmgr", "-v"), fake_process.Reply(missing=True))

    report = ventoy_observe_unit.run(bundle(scripted, tree(live=False)), arguments={})

    commands = report["commands"]
    assert isinstance(commands, dict)
    assert commands["firmware-entries"] == {
        "argv": ["efibootmgr", "-v"],
        "returncode": None,
        "error": "efibootmgr: not found",
    }

"""The installer disks unit runs the older script's steps, in order, through the ports."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_extents,
    fake_files,
    fake_ids,
    fake_process,
)
from apex.agent import agentports, builder
from apex.agent.units import installer_disks_unit
from apex.config import defaults
from apex.kernel import errors, quantities, refusals, safepaths

LOOP = "/dev/loop0"
TABLE = {"partitiontable": {"label": "gpt", "partitions": []}}
PRIVATE = quantities.FileMode(0o600)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "output").mkdir()
    for name in ("other.qcow2", "target.qcow2"):
        (tmp_path / "output" / name).write_bytes(name.encode())
    return tmp_path


def expected_steps(root: Path) -> list[tuple[str, ...]]:
    work = str(root / "work")
    raw = f"{work}/other.raw"
    mount = f"{work}/mnt"
    steps: list[tuple[str, ...]] = [
        ("systemd-detect-virt", "--vm"),
        ("dnf5", "-y", "install", "dosfstools", "e2fsprogs", "ntfs-3g", "ntfsprogs", "qemu-img",
         "util-linux-core"),
        ("truncate", "-s", "4G", raw),
        ("sfdisk", raw),
        ("losetup", "--find", "--show", "--partscan", raw),
    ]
    formats = (
        ("mkfs.vfat", "-F", "32", "-n", "APEX_EFI", f"{LOOP}p1"),
        ("mkfs.ntfs", "-Q", "-L", "APEX_WINDOWS", f"{LOOP}p2"),
        ("mkfs.ext4", "-L", "APEX_LINUX", f"{LOOP}p3"),
    )
    for index, argv in enumerate(formats, 1):
        steps += [
            argv,
            ("mount", "-t", argv[-2] if index != 2 else "ntfs-3g", "-o", "nosuid,nodev,noexec",
             f"{LOOP}p{index}", mount),
            ("umount", mount),
        ]
    steps[6] = ("mount", "-t", "vfat", "-o", "nosuid,nodev,noexec", f"{LOOP}p1", mount)
    steps[12] = ("mount", "-t", "ext4", "-o", "nosuid,nodev,noexec", f"{LOOP}p3", mount)
    steps += [
        ("losetup", "--detach", LOOP),
        ("qemu-img", "convert", "-f", "raw", "-O", "qcow2", raw, f"{root}/output/other.qcow2"),
        ("qemu-img", "create", "-f", "qcow2", f"{root}/output/target.qcow2", "48G"),
        ("sfdisk", "--json", raw),
    ]
    return steps


def bundle(root: Path, *, builder: bool = True) -> agentports.AgentPorts:
    process = fake_process.ScriptedProcess()
    for step in expected_steps(root):
        process.expect(step, fake_process.Reply())
    process.expect(("systemd-detect-virt", "--vm"), fake_process.Reply(stdout=b"kvm\n"))
    process.expect(
        ("losetup", "--find", "--show", "--partscan", f"{root}/work/other.raw"),
        fake_process.Reply(stdout=f"{LOOP}\n".encode()),
    )
    process.expect(
        ("sfdisk", "--json", f"{root}/work/other.raw"),
        fake_process.Reply(stdout=json.dumps(TABLE).encode()),
    )
    files = fake_files.MemoryFiles()
    marker = b"apex-isolated-builder-v1\n" if builder else b"someone else\n"
    files.write_atomic(safepaths.SafePath(Path(defaults.BUILDER_MARKER)), marker, mode=PRIVATE)
    files.write_atomic(
        safepaths.SafePath(Path("/sys/class/block/loop0/loop/backing_file")),
        f"{root}/work/other.raw\n".encode(), mode=PRIVATE,
    )
    for index in (1, 2, 3):
        files.write_atomic(safepaths.SafePath(Path(f"{LOOP}p{index}")), b"", mode=PRIVATE)
    return agentports.AgentPorts(
        processes=process,
        files=files,
        clock=fake_clock.ManualClock(),
        containers=fake_containers.FakeRegistry(),
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(),
    )


def arguments(root: Path) -> dict[str, str]:
    return {"work": str(root / "work"), "output": str(root / "output"), "token": "a" * 32}


def test_the_unit_runs_the_older_steps_in_order(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    ports = bundle(root)

    installer_disks_unit.run(ports, arguments=arguments(root))

    assert isinstance(ports.processes, fake_process.ScriptedProcess)
    assert [tuple(call) for call in ports.processes.calls] == expected_steps(root)


def test_the_report_has_the_older_shape(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    ports = bundle(root)

    report = installer_disks_unit.run(ports, arguments=arguments(root))

    assert report["bootable_existing_systems"] is False
    assert report["layout"] == TABLE
    partitions = report["partitions"]
    assert isinstance(partitions, list)
    assert [item["partition"] for item in partitions] == [1, 2, 3]  # type: ignore[index]
    assert set(report["sha256"]) == {"other.qcow2", "target.qcow2"}  # type: ignore[arg-type]
    assert isinstance(ports.files, fake_files.MemoryFiles)
    assert f"{root}/output/fixtures.json" in ports.files.writes
    assert f"{root}/work/mnt/EFI/BOOT/apex-sentinel.txt" in ports.files.writes


def test_a_guest_that_is_not_the_builder_is_refused_before_any_step(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    ports = bundle(root, builder=False)

    with pytest.raises(errors.Refusal) as raised:
        installer_disks_unit.run(ports, arguments=arguments(root))

    assert raised.value.reason is refusals.RefusalReason.BUILDER_NOT_ISOLATED
    assert isinstance(ports.processes, fake_process.ScriptedProcess)
    assert ports.processes.calls == []


def test_a_loop_device_that_is_not_ours_is_refused_and_detached(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    ports = bundle(root)
    assert isinstance(ports.files, fake_files.MemoryFiles)
    ports.files.write_atomic(
        safepaths.SafePath(Path("/sys/class/block/loop0/loop/backing_file")),
        b"/var/tmp/somebody-else.raw\n", mode=PRIVATE,
    )

    with pytest.raises(errors.Refusal) as raised:
        installer_disks_unit.run(ports, arguments=arguments(root))

    assert raised.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED

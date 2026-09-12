"""Fake guests with the disk fixtures the live faults expect, built once per test.

A spec names each device the way the older tests did; the tree and the block devices are
derived from it so a test mutates one line and both views change together.
"""

from __future__ import annotations

import dataclasses
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
from apex.ports import files as files_port

SYSFS = safepaths.SafePath(Path("/sys/class/block"))
PCI = safepaths.SafePath(Path("/sys/devices/pci0000:00"))
PUBLIC = quantities.FileMode(0o444)
CMDLINE = f"BOOT_IMAGE=/vmlinuz {defaults.LIVE_ROOT_TOKEN} quiet\n"
MOUNTINFO = "22 1 0:21 / / rw - overlay overlay rw\n"
SWAPS = "Filename Type Size Used Priority\n/dev/zram0 partition 4194300 0 100\n"


@dataclasses.dataclass(frozen=True, slots=True)
class DeviceSpec:
    name: str
    sectors: int
    partition: int | None = None
    serial: str | None = None
    parent: str | None = None
    ro: str = "1"
    bus: str = "virtio1"
    holders: tuple[str, ...] = ()
    major: int = 253
    minor: int = 0


def virtio_fixture() -> list[DeviceSpec]:
    return [
        DeviceSpec("vda", 4 * 2**21, serial="apex-other-1", minor=0),
        DeviceSpec("vda1", 100, partition=1, parent="vda", minor=1),
        DeviceSpec("vda2", 100, partition=2, parent="vda", minor=2),
        DeviceSpec("vda3", 100, partition=3, parent="vda", minor=3),
        DeviceSpec("vdb", 48 * 2**21, bus="virtio2", minor=16),
    ]


def usb_fixture() -> list[DeviceSpec]:
    return [
        DeviceSpec("sda", 4 * 2**21, bus="usb1", major=8, minor=0),
        DeviceSpec("sda1", 100, partition=1, parent="sda", bus="usb1", major=8, minor=1),
        DeviceSpec("sda2", 100, partition=2, parent="sda", bus="usb1", major=8, minor=2),
        DeviceSpec("sda3", 100, partition=3, parent="sda", bus="usb1", major=8, minor=3),
    ]


def home_of(spec: DeviceSpec) -> safepaths.SafePath:
    if spec.bus.startswith("usb"):
        base = PCI / "0000:00:14.0" / spec.bus / "1-1" / "1-1:1.0" / "host2" / "block"
    else:
        base = PCI / "0000:00:04.0" / spec.bus / "block"
    if spec.partition is None:
        return base / spec.name
    return base / (spec.parent or spec.name) / spec.name


@dataclasses.dataclass(slots=True)
class Guest:
    files: fake_files.MemoryFiles
    blocks: fake_blockdevices.FakeBlockDevices
    process: fake_process.ScriptedProcess

    def ports(self) -> agentports.AgentPorts:
        return agentports.AgentPorts(
            processes=self.process, files=self.files, clock=fake_clock.ManualClock(),
            containers=fake_containers.FakeRegistry(), digests=fake_digesting.CountingDigests(),
            archives=fake_archives.MemoryArchives(), identities=fake_ids.SequenceIdentities(),
            extents=fake_extents.FakeExtents(), blocks=self.blocks,
        )


GUARD_TEXT = b"#!/bin/sh\nblockdev --setro \"$1\" || { : > /run/apex-protection-failed; exit 1; }\n"


def guest(
    specs: list[DeviceSpec],
    *,
    live: bool = True,
    mountinfo: str = MOUNTINFO,
    swaps: str = SWAPS,
    usb_serial: str | None = "apex-usb-fixture",
    initramfs: bool = False,
    files: fake_files.MemoryFiles | None = None,
) -> Guest:
    files = fake_files.MemoryFiles() if files is None else files
    if initramfs:
        files.write_atomic(safepaths.SafePath(Path(defaults.INITRD_RELEASE)), b"", mode=PUBLIC)
        files.write_atomic(
            safepaths.SafePath(Path(defaults.MOUNTS)), b"rootfs / rootfs rw 0 0\n", mode=PUBLIC
        )
        files.write_atomic(safepaths.SafePath(Path(defaults.LIVE_GUARD)), GUARD_TEXT, mode=PUBLIC)
    blocks = fake_blockdevices.FakeBlockDevices()
    process = fake_process.ScriptedProcess()
    process.expect(("systemd-detect-virt", "--vm"), fake_process.Reply(stdout=b"kvm\n"))
    process.expect(("udevadm", "settle", "--timeout=20"), fake_process.Reply())
    cmdline = CMDLINE if live else "root=/dev/vda3\n"
    files.write_atomic(safepaths.SafePath(Path("/proc/cmdline")), cmdline.encode(), mode=PUBLIC)
    files.write_atomic(
        safepaths.SafePath(Path("/proc/self/mountinfo")), mountinfo.encode(), mode=PUBLIC
    )
    files.write_atomic(safepaths.SafePath(Path("/proc/swaps")), swaps.encode(), mode=PUBLIC)
    files.make_directory(SYSFS, mode=PUBLIC)
    if usb_serial is not None:
        usb = PCI / "0000:00:14.0" / "usb1" / "1-1"
        files.write_atomic(usb / "idVendor", b"0781\n", mode=PUBLIC)
        files.write_atomic(usb / "idProduct", b"5583\n", mode=PUBLIC)
        files.write_atomic(usb / "serial", f"{usb_serial}\n".encode(), mode=PUBLIC)
    for spec in specs:
        home = home_of(spec)
        files.write_atomic(home / "dev", f"{spec.major}:{spec.minor}\n".encode(), mode=PUBLIC)
        files.write_atomic(home / "ro", f"{spec.ro}\n".encode(), mode=PUBLIC)
        files.write_atomic(home / "size", f"{spec.sectors}\n".encode(), mode=PUBLIC)
        if spec.partition is not None:
            files.write_atomic(home / "partition", f"{spec.partition}\n".encode(), mode=PUBLIC)
        else:
            files.make_directory(home / "slaves", mode=PUBLIC)
        if spec.serial is not None:
            files.write_atomic(home / "serial", f"{spec.serial}\n".encode(), mode=PUBLIC)
        files.make_directory(home / "holders", mode=PUBLIC)
        for holder in spec.holders:
            files.make_directory(home / "holders" / holder, mode=PUBLIC)
        files.symlink(SYSFS / spec.name, target=home)
        number = files_port.DeviceNumber(spec.major, spec.minor)
        node = safepaths.SafePath(Path("/dev") / spec.name)
        files.devices[str(node)] = number
        blocks.declare(node, fake_blockdevices.FakeNode(number=number, content=bytes(512)))
    return Guest(files=files, blocks=blocks, process=process)

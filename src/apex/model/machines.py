"""Virtual machine description.

Every device is a member of a closed union, and no member reaches host hardware. Passthrough
is not forbidden by a search for its name; it has no member to be spelt with.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Protocol, Self

from apex.kernel import commands, errors, quantities, refusals, safepaths

MAXIMUM_EXTRA_DISKS = 2
LOOPBACK = "127.0.0.1"
QEMU_PROGRAM = "qemu-system-x86_64"


class VmRole(enum.StrEnum):
    BUILDER = "builder"
    TEST = "test"

    @property
    def is_disposable(self) -> bool:
        return self is VmRole.TEST


class Device(Protocol):
    def render(self) -> tuple[str, ...]: ...


@dataclasses.dataclass(frozen=True, slots=True)
class Machine:
    processors: int
    memory: quantities.Mib

    def render(self) -> tuple[str, ...]:
        return (
            "-machine", "q35,accel=kvm",
            "-cpu", "host",
            "-smp", str(self.processors),
            "-m", str(self.memory.value),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Firmware:
    code: safepaths.SafePath
    variables: safepaths.SafePath
    code_read_only: bool = True

    def render(self) -> tuple[str, ...]:
        if not self.code_read_only:
            raise errors.InternalDefect("firmware code is always attached read only")
        return (
            "-drive", f"if=pflash,format=raw,readonly=on,file={self.code}",
            "-drive", f"if=pflash,format=raw,file={self.variables}",
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Display:
    def render(self) -> tuple[str, ...]:
        return ("-display", "none", "-vga", "none", "-device", "virtio-vga", "-monitor", "none")


@dataclasses.dataclass(frozen=True, slots=True)
class MonitorSocket:
    path: safepaths.SafePath

    def render(self) -> tuple[str, ...]:
        return ("-qmp", f"unix:{self.path},server=on,wait=off")


@dataclasses.dataclass(frozen=True, slots=True)
class SerialFile:
    path: safepaths.SafePath

    def render(self) -> tuple[str, ...]:
        return ("-serial", f"file:{self.path}")


@dataclasses.dataclass(frozen=True, slots=True)
class RootDisk:
    path: safepaths.SafePath
    discard_unmap: bool = False

    def render(self) -> tuple[str, ...]:
        options = f"if=virtio,format=qcow2,file={self.path}"
        return ("-drive", options + (",discard=unmap" if self.discard_unmap else ""))


@dataclasses.dataclass(frozen=True, slots=True)
class ExtraDisk:
    path: safepaths.SafePath
    index: int

    def render(self) -> tuple[str, ...]:
        name = f"apex-other-{self.index}"
        return (
            "-drive", f"if=none,id={name},format=qcow2,file={self.path}",
            "-device", f"virtio-blk-pci,drive={name},serial={name}",
        )


@dataclasses.dataclass(frozen=True, slots=True)
class Cdrom:
    path: safepaths.SafePath

    def render(self) -> tuple[str, ...]:
        return ("-drive", f"file={self.path},format=raw,media=cdrom,readonly=on")


@dataclasses.dataclass(frozen=True, slots=True)
class UsbController:
    def render(self) -> tuple[str, ...]:
        return ("-device", "qemu-xhci,id=apex-usb")


@dataclasses.dataclass(frozen=True, slots=True)
class UsbStorage:
    path: safepaths.SafePath
    boot_first: bool = True

    def render(self) -> tuple[str, ...]:
        options = "usb-storage,bus=apex-usb.0,drive=apex-boot-usb,serial=apex-ventoy-fixture"
        return (
            "-drive", f"if=none,id=apex-boot-usb,format=qcow2,file={self.path}",
            "-device", options + (",bootindex=1" if self.boot_first else ""),
        )


@dataclasses.dataclass(frozen=True, slots=True)
class RestrictedNet:
    forwarded_port: quantities.TcpPort
    role: VmRole

    def render(self) -> tuple[str, ...]:
        restriction = ",restrict=on" if self.role.is_disposable else ""
        forward = f"hostfwd=tcp:{LOOPBACK}:{self.forwarded_port}-:22"
        return (
            "-netdev", f"user,id=net0{restriction},{forward}",
            "-device", "virtio-net-pci,netdev=net0",
        )


@dataclasses.dataclass(frozen=True, slots=True)
class NoNetwork:
    def render(self) -> tuple[str, ...]:
        return ("-nic", "none")


type QemuDevice = (
    Machine | Firmware | Display | MonitorSocket | SerialFile | RootDisk | ExtraDisk
    | Cdrom | UsbController | UsbStorage | RestrictedNet | NoNetwork
)

DEVICE_TYPES: tuple[type, ...] = (
    Machine, Firmware, Display, MonitorSocket, SerialFile, RootDisk, ExtraDisk,
    Cdrom, UsbController, UsbStorage, RestrictedNet, NoNetwork,
)


@dataclasses.dataclass(frozen=True, slots=True)
class VmResources:
    memory: quantities.Mib
    processors: int


@dataclasses.dataclass(frozen=True, slots=True)
class VmSpec:
    role: VmRole
    resources: VmResources
    devices: tuple[QemuDevice, ...]
    extra_disks: tuple[safepaths.SafePath, ...]

    @classmethod
    def build(
        cls,
        *,
        role: VmRole,
        resources: VmResources,
        root_disk: safepaths.SafePath,
        firmware: Firmware,
        extra_disks: tuple[safepaths.SafePath, ...] = (),
        seed: safepaths.SafePath | None = None,
        network: RestrictedNet | None = None,
    ) -> Self:
        if extra_disks and not role.is_disposable:
            raise errors.Refusal(
                refusals.RefusalReason.DEVICE_NOT_PERMITTED_FOR_ROLE,
                subject=f"{len(extra_disks)} extra disks on a {role} machine",
                remedy="additional disks are restricted to disposable test machines",
            )
        if len(extra_disks) > MAXIMUM_EXTRA_DISKS:
            raise errors.Refusal(
                refusals.RefusalReason.TOO_MANY_DEVICES, subject=f"{len(extra_disks)} extra disks"
            )
        attached = [root_disk, *extra_disks]
        if len({str(item) for item in attached}) != len(attached):
            raise errors.Refusal(
                refusals.RefusalReason.DUPLICATE_DEVICE,
                subject="the same disk was attached more than once",
            )
        devices: list[QemuDevice] = [
            Machine(processors=resources.processors, memory=resources.memory),
            Display(),
            firmware,
            RootDisk(root_disk, discard_unmap=role is VmRole.BUILDER),
        ]
        if seed is not None:
            devices.append(Cdrom(seed))
        devices.extend(ExtraDisk(path, index) for index, path in enumerate(extra_disks, 1))
        devices.append(network if network is not None else NoNetwork())
        return cls(
            role=role, resources=resources, devices=tuple(devices), extra_disks=extra_disks
        )

    def render(self) -> commands.Argv:
        arguments: list[str] = ["-name", f"apex-{self.role}"]
        for device in self.devices:
            arguments.extend(device.render())
        return commands.Argv.of(QEMU_PROGRAM, *arguments)


@dataclasses.dataclass(frozen=True, slots=True)
class VmIdentity:
    process: int
    pidfd_inode: int
    boot_ticks: int
    monitor_socket_inode: int


@dataclasses.dataclass(frozen=True, slots=True)
class VmLease:
    identity: VmIdentity
    role: VmRole


@dataclasses.dataclass(frozen=True, slots=True)
class OwnedTestVm:
    identity: VmIdentity
    role: VmRole

    def __post_init__(self) -> None:
        if not self.role.is_disposable:
            raise errors.Refusal(
                refusals.RefusalReason.NOT_A_DISPOSABLE_MACHINE,
                subject=str(self.role),
                remedy="destructive operations accept only a disposable test machine",
            )

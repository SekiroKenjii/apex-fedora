"""A disposable test machine as one run describes it, and the run directory it writes into.

Every disk a test machine touches is a fresh overlay over a source inside the runtime root,
so a run never writes to what it was given; the firmware variables are copied twice, the
copy the machine writes and the one the comparison reads back against. Nothing here starts
a process; it lays the run out and describes the machine for the context that launches it.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from apex.config import defaults, loader
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.model import machines
from apex.ports import portset
from apex.provisioning import backingchain, runrecord


@dataclasses.dataclass(frozen=True, slots=True)
class TestRequest:
    disk: Path
    iso: Path | None = None
    medium: machines.Medium | None = None
    extra_disks: tuple[Path, ...] = ()
    guest_ssh: bool = False
    serial_console: bool = False
    usb_bus: bool = False
    boot_usb: Path | None = None

    def __post_init__(self) -> None:
        self._require_usb_consistent()
        if self.medium is not None and self.iso is None:
            raise errors.Refusal(
                refusals.RefusalReason.TOPOLOGY_INCONSISTENT,
                subject=f"a {self.medium} medium without an image to boot",
            )
        if self.iso is not None and self.medium is None:
            raise errors.Refusal(
                refusals.RefusalReason.TOPOLOGY_INCONSISTENT,
                subject="an image to boot without saying whether it is live or installer",
            )
        if len(self.extra_disks) > defaults.MAXIMUM_TEST_EXTRA_DISKS:
            raise errors.Refusal(
                refusals.RefusalReason.TOO_MANY_DEVICES,
                subject=f"{len(self.extra_disks)} extra disks",
            )

    def _require_usb_consistent(self) -> None:
        """A bootable usb image rides the emulated bus beside one other disk and nothing else."""
        if self.boot_usb is None:
            return
        if not self.usb_bus:
            raise errors.Refusal(
                refusals.RefusalReason.TOPOLOGY_INCONSISTENT,
                subject="a bootable usb image without the emulated usb bus",
                remedy="ask for the bus with the image",
            )
        if self.iso is not None or self.guest_ssh or len(self.extra_disks) != 1:
            raise errors.Refusal(
                refusals.RefusalReason.TOPOLOGY_INCONSISTENT,
                subject="usb boot",
                remedy="usb boot takes one other disk, no image to boot and no guest ssh",
            )


@dataclasses.dataclass(frozen=True, slots=True)
class Prepared:
    run: identifiers.RunId
    run_directory: safepaths.SafePath
    spec: machines.VmSpec
    medium: machines.Medium | None


def prepare(
    ports: portset.HostPorts,
    settings: loader.Settings,
    root: safepaths.RuntimeRoot,
    request: TestRequest,
    *,
    run: identifiers.RunId,
) -> Prepared:
    run_directory = root.child(f"{defaults.RUNS_DIRECTORY}/{run}")
    ports.files.make_directory(run_directory, mode=safepaths.PRIVATE_DIRECTORY_MODE)
    disk = _overlay(ports, request.disk, into=run_directory / defaults.TEST_DISK_NAME, root=root)
    extras = tuple(
        _overlay(
            ports, source,
            into=run_directory / f"{defaults.TEST_EXTRA_DISK_PREFIX}{index}.qcow2", root=root,
        )
        for index, source in enumerate(request.extra_disks, 1)
    )
    boot_usb = None
    boot_layer = None
    if request.boot_usb is not None:
        boot_usb = _overlay(
            ports, request.boot_usb, into=run_directory / defaults.TEST_BOOT_USB_NAME, root=root
        )
        boot_layer = runrecord.Layer(request.boot_usb, boot_usb.path)
    variables = _variables(ports, settings, run_directory)
    record = runrecord.RunRecord(
        run=run,
        disk=runrecord.Layer(request.disk, disk.path),
        extras=tuple(
            runrecord.Layer(source, overlay.path)
            for source, overlay in zip(request.extra_disks, extras, strict=True)
        ),
        iso=request.iso,
        medium=request.medium,
        guest_ssh=request.guest_ssh,
        serial_console=request.serial_console,
        usb_bus=request.usb_bus,
        boot_usb=boot_layer,
    )
    runrecord.write(ports, run_directory, record)
    spec = describe(
        settings, root, run_directory, disk=disk, extras=extras, variables=variables,
        iso=request.iso, guest_ssh=request.guest_ssh, serial_console=request.serial_console,
        usb_bus=request.usb_bus, boot_usb=boot_usb,
    )
    return Prepared(run=run, run_directory=run_directory, spec=spec, medium=request.medium)


def describe(  # noqa: PLR0913
    settings: loader.Settings,
    root: safepaths.RuntimeRoot,
    run_directory: safepaths.SafePath,
    *,
    disk: safepaths.SafePath,
    extras: tuple[safepaths.SafePath, ...],
    variables: safepaths.SafePath,
    iso: Path | None,
    guest_ssh: bool,
    serial_console: bool,
    usb_bus: bool,
    boot_usb: safepaths.SafePath | None,
) -> machines.VmSpec:
    """The machine over the overlays named, whether they were just made or are being resumed."""
    serial_log = run_directory / defaults.TEST_SERIAL_LOG_NAME
    serial: machines.Serial = machines.SerialFile(serial_log)
    if serial_console:
        serial = machines.SerialSocket(root.child(defaults.SERIAL_SOCKET_NAME), log=serial_log)
    code = safepaths.RegularFile.adopt(settings.builder.firmware_code)
    seed = None if iso is None else safepaths.SafePath.regular_file(iso, within=root)
    network = None
    if guest_ssh:
        network = machines.RestrictedNet(
            forwarded_port=defaults.TEST_MACHINE.ssh_port, role=machines.VmRole.TEST
        )
    return machines.VmSpec.build(
        role=machines.VmRole.TEST,
        resources=machines.VmResources(
            memory=defaults.TEST_MACHINE.memory, processors=defaults.TEST_MACHINE.processors
        ),
        root_disk=disk,
        firmware=machines.Firmware(code=safepaths.SafePath(code.path), variables=variables),
        monitor=machines.MonitorSocket(root.child(defaults.MONITOR_SOCKET_NAME)),
        serial=serial,
        extra_disks=extras,
        seed=seed,
        network=network,
        usb=machines.UsbController() if usb_bus else None,
        boot_usb=None if boot_usb is None else machines.UsbStorage(boot_usb),
        boot_from_cdrom=iso is not None,
    )


def _overlay(
    ports: portset.HostPorts,
    source: Path,
    *,
    into: safepaths.SafePath,
    root: safepaths.RuntimeRoot,
) -> safepaths.SafePath:
    chain = backingchain.inspect(ports, source, root=root)
    return backingchain.overlay(ports, chain, into=into, root=root).disk


def _variables(
    ports: portset.HostPorts, settings: loader.Settings, run_directory: safepaths.SafePath
) -> safepaths.SafePath:
    adopted = safepaths.RegularFile.adopt(settings.builder.firmware_variables)
    source = safepaths.SafePath(adopted.path)
    written = run_directory / defaults.VARIABLES_NAME
    ports.files.copy(source, written)
    ports.files.copy(source, run_directory / defaults.INITIAL_VARIABLES_NAME)
    return written

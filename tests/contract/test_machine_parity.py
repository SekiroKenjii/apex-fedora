"""Every argument list the older builder assembles is what the typed machine renders.

The older `vm.command` grows its list by hand and checks it afterwards with six forbidden
substrings. The machine here is a closed union of devices in a fixed order. For each topology
the older code can express, the two must agree word for word, because the order of `-drive`
and `-device` arguments decides the addresses a guest sees.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.config import defaults
from apex.kernel import quantities, safepaths
from apex.model import machines
from apexlib import common as legacy_common
from apexlib import vm as legacy

FIRMWARE_CODE = Path(legacy_common.config()["builder"]["firmware_code"])
MEMORY = 4096
PROCESSORS = 4


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "rt"
    base.mkdir(mode=0o700)
    if not FIRMWARE_CODE.is_file():
        pytest.skip(f"NOT TESTED: {FIRMWARE_CODE} is absent")
    return safepaths.RuntimeRoot.adopt(base)


def present(root: safepaths.RuntimeRoot, relative: str) -> safepaths.SafePath:
    target = root.path / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"")
    return safepaths.SafePath.regular_file(target, within=root)


def firmware(root: safepaths.RuntimeRoot, artifacts: str, role: str) -> machines.Firmware:
    return machines.Firmware(
        code=safepaths.SafePath(FIRMWARE_CODE),
        variables=present(root, f"{artifacts}/{role}-vars.fd"),
    )


def resources() -> machines.VmResources:
    return machines.VmResources(memory=quantities.Mib(MEMORY), processors=PROCESSORS)


def older(root: safepaths.RuntimeRoot, disk: str, role: str, **options: object) -> list[str]:
    artifacts = options.pop("artifacts", None)
    return legacy.command(
        root.path,
        root.path / disk,
        role,
        MEMORY,
        PROCESSORS,
        artifacts_dir=None if artifacts is None else root.path / str(artifacts),
        **options,  # type: ignore[arg-type]
    )


def test_the_builder_topology(root: safepaths.RuntimeRoot) -> None:
    disk = present(root, "builder.qcow2")
    seed = present(root, "seed.iso")
    spec = machines.VmSpec.build(
        role=machines.VmRole.BUILDER,
        resources=resources(),
        root_disk=disk,
        firmware=firmware(root, ".", "builder"),
        monitor=machines.MonitorSocket(root.child("qmp.sock")),
        serial=machines.SerialFile(root.child("builder-serial.log")),
        seed=seed,
        network=machines.RestrictedNet(
            forwarded_port=defaults.BUILDER_SSH_PORT, role=machines.VmRole.BUILDER
        ),
    )

    assert list(spec.render()) == older(
        root, "builder.qcow2", "builder", seed=seed.path, port=defaults.BUILDER_SSH_PORT.value
    )


def test_a_sealed_test_machine(root: safepaths.RuntimeRoot) -> None:
    disk = present(root, "runs/a/disk.qcow2")
    spec = machines.VmSpec.build(
        role=machines.VmRole.TEST,
        resources=resources(),
        root_disk=disk,
        firmware=firmware(root, "runs/a", "test"),
        monitor=machines.MonitorSocket(root.child("qmp.sock")),
        serial=machines.SerialFile(root.child("runs/a/test-serial.log")),
    )

    assert list(spec.render()) == older(root, "runs/a/disk.qcow2", "test", artifacts="runs/a")


def test_an_installer_test_boots_its_iso_and_answers_on_loopback(
    root: safepaths.RuntimeRoot,
) -> None:
    disk = present(root, "runs/a/disk.qcow2")
    iso = present(root, "installer.iso")
    spec = machines.VmSpec.build(
        role=machines.VmRole.TEST,
        resources=resources(),
        root_disk=disk,
        firmware=firmware(root, "runs/a", "test"),
        monitor=machines.MonitorSocket(root.child("qmp.sock")),
        serial=machines.SerialFile(root.child("runs/a/test-serial.log")),
        seed=iso,
        network=machines.RestrictedNet(
            forwarded_port=defaults.GUEST_SSH_PORT, role=machines.VmRole.TEST
        ),
        boot_from_cdrom=True,
    )
    expected = older(
        root, "runs/a/disk.qcow2", "test", seed=iso.path, port=defaults.GUEST_SSH_PORT.value,
        artifacts="runs/a",
    ) + ["-boot", "order=d"]

    assert list(spec.render()) == expected


def test_two_extra_disks_keep_their_indices(root: safepaths.RuntimeRoot) -> None:
    disk = present(root, "runs/a/disk.qcow2")
    extras = (present(root, "runs/a/other-1.qcow2"), present(root, "runs/a/other-2.qcow2"))
    spec = machines.VmSpec.build(
        role=machines.VmRole.TEST,
        resources=resources(),
        root_disk=disk,
        firmware=firmware(root, "runs/a", "test"),
        monitor=machines.MonitorSocket(root.child("qmp.sock")),
        serial=machines.SerialFile(root.child("runs/a/test-serial.log")),
        extra_disks=extras,
    )

    assert list(spec.render()) == older(
        root, "runs/a/disk.qcow2", "test", artifacts="runs/a",
        extra_disks=tuple(item.path for item in extras),
    )


def test_a_serial_socket_replaces_the_serial_file_in_place(root: safepaths.RuntimeRoot) -> None:
    disk = present(root, "runs/a/disk.qcow2")
    spec = machines.VmSpec.build(
        role=machines.VmRole.TEST,
        resources=resources(),
        root_disk=disk,
        firmware=firmware(root, "runs/a", "test"),
        monitor=machines.MonitorSocket(root.child("qmp.sock")),
        serial=machines.SerialSocket(
            root.child("serial.sock"), root.child("runs/a/test-serial.log")
        ),
    )

    assert list(spec.render()) == older(
        root, "runs/a/disk.qcow2", "test", artifacts="runs/a", serial_console=True
    )


def test_an_emulated_usb_bus_without_media(root: safepaths.RuntimeRoot) -> None:
    disk = present(root, "runs/a/disk.qcow2")
    spec = machines.VmSpec.build(
        role=machines.VmRole.TEST,
        resources=resources(),
        root_disk=disk,
        firmware=firmware(root, "runs/a", "test"),
        monitor=machines.MonitorSocket(root.child("qmp.sock")),
        serial=machines.SerialFile(root.child("runs/a/test-serial.log")),
        usb=machines.UsbController(),
    )

    assert list(spec.render()) == older(
        root, "runs/a/disk.qcow2", "test", artifacts="runs/a", usb_test_bus=True
    )


def test_usb_boot_places_the_media_after_the_other_disk(root: safepaths.RuntimeRoot) -> None:
    disk = present(root, "runs/a/disk.qcow2")
    other = present(root, "runs/a/other-1.qcow2")
    media = present(root, "runs/a/other-2.qcow2")
    spec = machines.VmSpec.build(
        role=machines.VmRole.TEST,
        resources=resources(),
        root_disk=disk,
        firmware=firmware(root, "runs/a", "test"),
        monitor=machines.MonitorSocket(root.child("qmp.sock")),
        serial=machines.SerialFile(root.child("runs/a/test-serial.log")),
        extra_disks=(other,),
        usb=machines.UsbController(),
        boot_usb=machines.UsbStorage(media),
    )

    assert list(spec.render()) == older(
        root, "runs/a/disk.qcow2", "test", artifacts="runs/a",
        extra_disks=(other.path, media.path), boot_usb=True,
    )

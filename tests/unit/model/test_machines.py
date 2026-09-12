"""Host passthrough is not a device this program can describe.

The current builder assembles an argument list by hand and defends it with a search for six
forbidden substrings. Here the device union simply has no member that reaches the host.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.kernel import errors, quantities, refusals, safepaths
from apex.model import machines


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def disk(root: safepaths.RuntimeRoot, name: str) -> safepaths.SafePath:
    target = root.path / name
    target.write_bytes(b"")
    return safepaths.SafePath.regular_file(target, within=root)


def build(root: safepaths.RuntimeRoot, **overrides: object) -> machines.VmSpec:
    arguments: dict[str, object] = {
        "role": machines.VmRole.TEST,
        "resources": machines.VmResources(memory=quantities.Mib(4096), processors=4),
        "root_disk": disk(root, "disk.qcow2"),
        "firmware": machines.Firmware(code=disk(root, "code.fd"), variables=disk(root, "vars.fd")),
        "monitor": machines.MonitorSocket(root.child("qmp.sock")),
        "serial": machines.SerialFile(root.child("serial.log")),
    }
    arguments.update(overrides)
    return machines.VmSpec.build(**arguments)  # type: ignore[arg-type]


def test_the_device_union_has_no_member_that_reaches_host_hardware() -> None:
    names = {member.__name__.lower() for member in machines.DEVICE_TYPES}

    for forbidden in ("vfio", "usbhost", "virtfs", "tap", "bridge", "passthrough"):
        assert not any(forbidden in name for name in names)


def test_firmware_code_is_always_read_only(root: safepaths.RuntimeRoot) -> None:
    firmware = machines.Firmware(code=disk(root, "code.fd"), variables=disk(root, "vars.fd"))

    assert firmware.code_read_only


def test_firmware_cannot_be_built_writable(root: safepaths.RuntimeRoot) -> None:
    firmware = machines.Firmware(code=disk(root, "code.fd"), variables=disk(root, "vars.fd"))

    with pytest.raises(errors.InternalDefect):
        object.__setattr__(firmware, "code_read_only", False)
        firmware.render()


def test_a_test_network_is_restricted(root: safepaths.RuntimeRoot) -> None:
    network = machines.RestrictedNet(
        forwarded_port=quantities.TcpPort(22245), role=machines.VmRole.TEST
    )

    assert "restrict=on" in ",".join(network.render())


def test_a_builder_network_is_not_restricted(root: safepaths.RuntimeRoot) -> None:
    network = machines.RestrictedNet(
        forwarded_port=quantities.TcpPort(22244), role=machines.VmRole.BUILDER
    )

    assert "restrict=on" not in ",".join(network.render())


def test_a_forwarded_port_binds_only_to_loopback(root: safepaths.RuntimeRoot) -> None:
    rendered = ",".join(
        machines.RestrictedNet(
            forwarded_port=quantities.TcpPort(22245), role=machines.VmRole.TEST
        ).render()
    )

    assert "127.0.0.1" in rendered
    assert "0.0.0.0" not in rendered


def test_extra_disks_are_refused_outside_a_disposable_test_machine(
    root: safepaths.RuntimeRoot,
) -> None:
    with pytest.raises(errors.Refusal) as raised:
        build(root, role=machines.VmRole.BUILDER, extra_disks=(disk(root, "other.qcow2"),))

    assert raised.value.reason is refusals.RefusalReason.DEVICE_NOT_PERMITTED_FOR_ROLE


def test_a_test_machine_accepts_up_to_two_extra_disks(root: safepaths.RuntimeRoot) -> None:
    spec = build(root, extra_disks=(disk(root, "a.qcow2"), disk(root, "b.qcow2")))

    assert len(spec.extra_disks) == 2


def test_a_third_extra_disk_is_refused(root: safepaths.RuntimeRoot) -> None:
    with pytest.raises(errors.Refusal):
        build(
            root,
            extra_disks=(disk(root, "a.qcow2"), disk(root, "b.qcow2"), disk(root, "c.qcow2")),
        )


def test_a_repeated_disk_is_refused(root: safepaths.RuntimeRoot) -> None:
    same = disk(root, "a.qcow2")

    with pytest.raises(errors.Refusal) as raised:
        build(root, extra_disks=(same, same))

    assert raised.value.reason is refusals.RefusalReason.DUPLICATE_DEVICE


def test_the_root_disk_cannot_also_be_an_extra_disk(root: safepaths.RuntimeRoot) -> None:
    shared = disk(root, "disk.qcow2")

    with pytest.raises(errors.Refusal):
        build(root, extra_disks=(shared,))


def test_a_rendered_specification_names_the_program_first(root: safepaths.RuntimeRoot) -> None:
    spec = build(root, role=machines.VmRole.BUILDER)

    assert tuple(spec.render())[0] == "qemu-system-x86_64"


def test_a_rendered_specification_never_contains_a_host_device(
    root: safepaths.RuntimeRoot,
) -> None:
    spec = build(root)
    rendered = " ".join(spec.render())

    for forbidden in ("vfio", "usb-host", "virtfs", "if=tap", "bridge"):
        assert forbidden not in rendered


def test_an_owned_test_machine_compares_four_identity_fields() -> None:
    identity = machines.VmIdentity(
        process=1234, pidfd_inode=99, boot_ticks=555, monitor_socket_inode=77
    )

    assert identity == machines.VmIdentity(
        process=1234, pidfd_inode=99, boot_ticks=555, monitor_socket_inode=77
    )
    assert identity != machines.VmIdentity(
        process=1234, pidfd_inode=99, boot_ticks=556, monitor_socket_inode=77
    )


def test_only_a_disposable_machine_can_be_owned() -> None:
    identity = machines.VmIdentity(
        process=1, pidfd_inode=2, boot_ticks=3, monitor_socket_inode=4
    )

    with pytest.raises(errors.Refusal) as raised:
        machines.OwnedTestVm(identity=identity, role=machines.VmRole.BUILDER)

    assert raised.value.reason is refusals.RefusalReason.NOT_A_DISPOSABLE_MACHINE


def test_a_disposable_machine_is_owned_without_complaint() -> None:
    identity = machines.VmIdentity(
        process=1, pidfd_inode=2, boot_ticks=3, monitor_socket_inode=4
    )

    owned = machines.OwnedTestVm(identity=identity, role=machines.VmRole.TEST)

    assert owned.role is machines.VmRole.TEST


def test_a_serial_socket_is_refused_outside_a_disposable_test_machine(
    root: safepaths.RuntimeRoot,
) -> None:
    serial = machines.SerialSocket(root.child("serial.sock"), root.child("serial.log"))

    with pytest.raises(errors.Refusal) as raised:
        build(root, role=machines.VmRole.BUILDER, serial=serial)

    assert raised.value.reason is refusals.RefusalReason.DEVICE_NOT_PERMITTED_FOR_ROLE


def test_a_serial_socket_path_must_fit_the_kernel_limit(root: safepaths.RuntimeRoot) -> None:
    long = root.child("s" * machines.SOCKET_PATH_LIMIT)

    with pytest.raises(errors.Refusal) as raised:
        machines.SerialSocket(long, root.child("serial.log"))

    assert raised.value.reason is refusals.RefusalReason.SOCKET_PATH_TOO_LONG


def test_usb_boot_takes_the_controller_and_exactly_one_other_disk(
    root: safepaths.RuntimeRoot,
) -> None:
    spec = build(
        root,
        usb=machines.UsbController(),
        extra_disks=(disk(root, "other.qcow2"),),
        boot_usb=machines.UsbStorage(disk(root, "ventoy.qcow2")),
    )
    rendered = " ".join(spec.render())

    assert "bootindex=1" in rendered
    assert "apex-other-1" in rendered


@pytest.mark.parametrize(
    "overrides",
    [
        {"extra_disks": ()},
        {"seed": "seed.iso"},
        {"network": "restricted"},
        {"usb": None},
    ],
)
def test_usb_boot_with_anything_else_is_refused(
    root: safepaths.RuntimeRoot, overrides: dict[str, object]
) -> None:
    arguments: dict[str, object] = {
        "usb": machines.UsbController(),
        "extra_disks": (disk(root, "other.qcow2"),),
        "boot_usb": machines.UsbStorage(disk(root, "ventoy.qcow2")),
    }
    if overrides.get("seed"):
        overrides["seed"] = disk(root, "seed.iso")
    if overrides.get("network"):
        overrides["network"] = machines.RestrictedNet(
            forwarded_port=quantities.TcpPort(22245), role=machines.VmRole.TEST
        )
    arguments.update(overrides)

    with pytest.raises(errors.Refusal) as raised:
        build(root, **arguments)

    assert raised.value.reason is refusals.RefusalReason.TOPOLOGY_INCONSISTENT


def test_booting_from_a_cdrom_requires_one_to_be_attached(root: safepaths.RuntimeRoot) -> None:
    with pytest.raises(errors.Refusal) as raised:
        build(root, boot_from_cdrom=True)

    assert raised.value.reason is refusals.RefusalReason.TOPOLOGY_INCONSISTENT


def test_a_cdrom_boot_renders_last(root: safepaths.RuntimeRoot) -> None:
    spec = build(root, seed=disk(root, "installer.iso"), boot_from_cdrom=True)

    assert tuple(spec.render())[-2:] == ("-boot", "order=d")


def test_the_builder_root_disk_reclaims_deleted_blocks(root: safepaths.RuntimeRoot) -> None:
    spec = build(root, role=machines.VmRole.BUILDER)

    assert any("discard=unmap" in item for item in spec.render())

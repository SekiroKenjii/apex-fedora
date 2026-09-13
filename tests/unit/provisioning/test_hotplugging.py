"""A USB fixture is attached to the running test machine as a fresh layer, recorded first."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from machinehost import RUN, Host
from storagefixtures import Storage

from apex.adapters.fakes import fake_qmp
from apex.config import defaults
from apex.kernel import errors, quantities, refusals, safepaths
from apex.model import machines
from apex.provisioning import hotplugging, launching


def spec(
    host: Host, *, role: machines.VmRole = machines.VmRole.TEST, usb: bool = True
) -> machines.VmSpec:
    present = {}
    for name in ("disk.qcow2", "code.fd", "vars.fd"):
        target = host.root.path / name
        target.write_bytes(b"")
        present[name] = safepaths.SafePath.regular_file(target, within=host.root)
    return machines.VmSpec.build(
        role=role,
        resources=machines.VmResources(memory=quantities.Mib(4096), processors=4),
        root_disk=present["disk.qcow2"],
        firmware=machines.Firmware(code=present["code.fd"], variables=present["vars.fd"]),
        monitor=machines.MonitorSocket(host.root.child("qmp.sock")),
        serial=machines.SerialFile(host.root.child("serial.log")),
        usb=machines.UsbController() if usb and role is machines.VmRole.TEST else None,
    )


def started(host: Host, **changes: object) -> Host:
    held = dataclasses.replace(host, ports=dataclasses.replace(host.ports, processes=Storage()))
    host.run_directory.path.mkdir(parents=True, exist_ok=True)
    launching.launch(
        held.ports, root=held.root, spec=spec(held, **changes), run=RUN,  # type: ignore[arg-type]
        run_directory=held.run_directory,
    )
    host.monitor.reply(hotplugging.BLOCKDEV_ADD, {})
    host.monitor.reply(hotplugging.DEVICE_ADD, {})
    return held


def fixture(host: Host) -> Path:
    target = host.root.path / "fixture.qcow2"
    target.write_bytes(b"")
    return target


def record(host: Host) -> dict[str, object]:
    path = safepaths.SafePath(host.run_directory.path / defaults.HOTPLUG_RECORD)
    loaded: dict[str, object] = json.loads(host.files.read_bytes(path, limit=1 << 20))
    return loaded


def test_the_fixture_is_layered_registered_and_attached_through_the_bus(host: Host) -> None:
    held = started(host)
    overlay = host.run_directory.path / defaults.HOTPLUG_OVERLAY_NAME

    report = hotplugging.attach(held.ports, root=held.root, source=fixture(host))

    assert report.status == hotplugging.ATTACHED
    assert report.overlay.path == overlay and overlay.is_file()
    assert [command.name for command in host.monitor.executed] == ["blockdev-add", "device_add"]
    added, device = host.monitor.executed
    assert added.arguments["node-name"] == "apex-usb-disk"
    assert added.arguments["file"] == {"driver": "file", "filename": str(overlay)}  # type: ignore[comparison-overlap]
    assert device.arguments["bus"] == "apex-usb.0"
    assert device.arguments["serial"] == "apex-usb-fixture"
    assert device.arguments["driver"] == "usb-storage"
    assert device.arguments["drive"] == "apex-usb-disk"
    written = record(host)
    assert written["status"] == "ATTACHED" and written["responses"] == [{}, {}]
    assert written["guest_protection"] == "NOT TESTED"
    assert host.files.writes.count(str(host.run_directory.path / defaults.HOTPLUG_RECORD)) == 2


def test_without_a_running_machine_nothing_is_attached(host: Host) -> None:
    with pytest.raises(errors.Refusal) as raised:
        hotplugging.attach(host.ports, root=host.root, source=fixture(host))

    assert raised.value.reason is refusals.RefusalReason.MACHINE_NOT_RUNNING


def test_a_builder_takes_no_fixture(host: Host) -> None:
    held = started(host, role=machines.VmRole.BUILDER)

    with pytest.raises(errors.Refusal) as raised:
        hotplugging.attach(held.ports, root=held.root, source=fixture(host))

    assert raised.value.reason is refusals.RefusalReason.NOT_A_DISPOSABLE_MACHINE


def test_a_test_machine_without_the_bus_is_refused_before_any_overlay(host: Host) -> None:
    held = started(host, usb=False)

    with pytest.raises(errors.Refusal) as raised:
        hotplugging.attach(held.ports, root=held.root, source=fixture(host))

    assert raised.value.reason is refusals.RefusalReason.TOPOLOGY_INCONSISTENT
    assert not (host.run_directory.path / defaults.HOTPLUG_OVERLAY_NAME).exists()
    assert host.monitor.executed == []


def test_one_fixture_per_run(host: Host) -> None:
    held = started(host)
    hotplugging.attach(held.ports, root=held.root, source=fixture(host))

    with pytest.raises(errors.Refusal) as raised:
        hotplugging.attach(held.ports, root=held.root, source=fixture(host))

    assert raised.value.reason is refusals.RefusalReason.DUPLICATE_DEVICE
    assert [command.name for command in host.monitor.executed] == ["blockdev-add", "device_add"]


def test_a_monitor_that_refuses_the_device_leaves_the_record_incomplete(host: Host) -> None:
    held = started(host)
    refusing = fake_qmp.ScriptedQmp({hotplugging.BLOCKDEV_ADD: {}})
    held = dataclasses.replace(held, ports=dataclasses.replace(held.ports, monitor=refusing))

    with pytest.raises(errors.PortFailure):
        hotplugging.attach(held.ports, root=held.root, source=fixture(host))

    written = json.loads(
        held.files.read_bytes(
            safepaths.SafePath(held.run_directory.path / defaults.HOTPLUG_RECORD), limit=1 << 20
        )
    )
    assert written["status"] == "INCOMPLETE" and written["responses"] == [{}]


def test_the_attached_fixture_reads_back_as_a_layer_and_nothing_before(host: Host) -> None:
    held = started(host)

    assert hotplugging.attached(held.ports, held.run_directory) is None
    report = hotplugging.attach(held.ports, root=held.root, source=fixture(host))

    layer = hotplugging.attached(held.ports, held.run_directory)
    assert layer is not None
    assert layer.source == report.source.path and layer.overlay == report.overlay.path

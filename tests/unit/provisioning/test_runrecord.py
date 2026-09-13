"""A run's record says what it was started from, and reads back exactly as written."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from machinehost import RUN, Host

from apex.config import defaults
from apex.kernel import errors, refusals, safepaths
from apex.model import machines
from apex.provisioning import runrecord

RECORD = runrecord.RunRecord(
    run=RUN,
    disk=runrecord.Layer(Path("/r/target.qcow2"), Path("/r/vm-runs/x/disk.qcow2")),
    extras=(runrecord.Layer(Path("/r/other.qcow2"), Path("/r/vm-runs/x/other-1.qcow2")),),
    iso=Path("/r/apex.iso"),
    medium=machines.Medium.INSTALLER,
    guest_ssh=True,
    serial_console=False,
    usb_bus=False,
    boot_usb=None,
)


def test_the_record_round_trips_through_its_document() -> None:
    document = json.loads(json.dumps(RECORD.document()))

    assert runrecord.RunRecord.parse(document) == RECORD
    assert document["medium"] == "installer" and document["schema"] == 1


def test_the_layers_list_every_overlay_with_the_fixture_last() -> None:
    hotplug = runrecord.Layer(Path("/r/fixture.qcow2"), Path("/r/vm-runs/x/hotplug-usb.qcow2"))
    boot = runrecord.Layer(Path("/r/ventoy.qcow2"), Path("/r/vm-runs/x/boot-usb.qcow2"))
    with_boot = dataclasses.replace(RECORD, usb_bus=True, boot_usb=boot, iso=None, medium=None)

    assert RECORD.layers() == (RECORD.disk, *RECORD.extras)
    assert with_boot.layers(hotplug) == (RECORD.disk, *RECORD.extras, boot, hotplug)


def test_a_record_is_written_beside_the_overlays_and_read_back(host: Host) -> None:
    host.run_directory.path.mkdir(parents=True)

    runrecord.write(host.ports, host.run_directory, RECORD)

    path = str(host.run_directory.path / defaults.RUN_RECORD_NAME)
    assert path in host.files.writes
    assert runrecord.read(host.ports, host.run_directory) == RECORD


def test_a_run_without_a_record_is_refused_by_name(host: Host) -> None:
    with pytest.raises(errors.Refusal) as raised:
        runrecord.read(host.ports, host.run_directory)

    assert raised.value.reason is refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE


@pytest.mark.parametrize(
    "payload", [b"{", b"[]", b'{"run": "x"}', b'{"run": "' + b"a" * 32 + b'", "disk": 3}']
)
def test_a_record_of_another_shape_is_refused(host: Host, payload: bytes) -> None:
    host.files.write_atomic(
        safepaths.SafePath(host.run_directory.path / defaults.RUN_RECORD_NAME), payload,
        mode=defaults.RECORD_MODE,
    )

    with pytest.raises(errors.Refusal) as raised:
        runrecord.read(host.ports, host.run_directory)

    assert raised.value.reason is refusals.RefusalReason.LEASE_MALFORMED

"""A stopped run boots again over its own overlays, with the earlier boot's evidence kept."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from machinehost import RUN, Host
from storagefixtures import Storage

from apex.config import defaults, loader
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.model import machines
from apex.provisioning import launching, resuming, testspec

STAMP = identifiers.Token("5" * 32)
PRIVATE = defaults.RECORD_MODE


def settings(tmp_path: Path) -> loader.Settings:
    for name in ("OVMF_CODE.fd", "OVMF_VARS.fd"):
        (tmp_path / name).write_bytes(name.encode())
    host = tmp_path / "settings.toml"
    host.write_text(
        f'[builder]\nfirmware_code = "{tmp_path}/OVMF_CODE.fd"\n'
        f'firmware_variables = "{tmp_path}/OVMF_VARS.fd"\n'
    )
    return loader.load(host_file=host, environment={})


def started(host: Host, tmp_path: Path, **changes: object) -> testspec.Prepared:
    """A run prepared the way the command prepares it, with its overlays on disk."""
    held = settings(tmp_path)
    host.files.write_atomic(
        safepaths.SafePath(held.builder.firmware_variables), b"vars", mode=PRIVATE
    )
    for name in ("target.qcow2", "other.qcow2", "apex.iso", "ventoy.qcow2"):
        (host.root.path / name).write_bytes(b"")
    request = testspec.TestRequest(
        disk=host.root.path / "target.qcow2", **changes,  # type: ignore[arg-type]
    )
    ports = dataclasses.replace(host.ports, processes=Storage())
    prepared = testspec.prepare(ports, held, host.root, request, run=RUN)
    host.files.write_atomic(
        safepaths.SafePath(prepared.run_directory.path / defaults.TEST_SERIAL_LOG_NAME),
        b"first boot", mode=PRIVATE,
    )
    return prepared


def test_the_run_is_rebuilt_over_its_overlays_without_remaking_them(
    host: Host, tmp_path: Path
) -> None:
    first = started(
        host, tmp_path, iso=host.root.path / "apex.iso", medium=machines.Medium.INSTALLER,
        extra_disks=(host.root.path / "other.qcow2",), guest_ssh=True,
    )
    tools = Storage()
    ports = dataclasses.replace(host.ports, processes=tools)

    resumed = resuming.resume(
        ports, settings(tmp_path), host.root, RUN, stamp=STAMP, without_iso=False
    )

    assert resumed.run == RUN and resumed.run_directory == first.run_directory
    assert resumed.medium is machines.Medium.INSTALLER
    assert list(resumed.spec.render()) == list(first.spec.render())
    assert tools.calls == []
    run_directory = host.run_directory.path
    for suffix in ("-vars.fd", "-serial.log", ".json"):
        assert str(run_directory / f"before-resume-{STAMP}{suffix}") in host.files.writes
    assert host.files.read_bytes(
        safepaths.SafePath(run_directory / f"before-resume-{STAMP}-serial.log"), limit=1 << 20
    ) == b"first boot"


def test_without_the_iso_the_installed_disk_boots_on_its_own(host: Host, tmp_path: Path) -> None:
    started(host, tmp_path, iso=host.root.path / "apex.iso", medium=machines.Medium.INSTALLER)

    resumed = resuming.resume(
        host.ports, settings(tmp_path), host.root, RUN, stamp=STAMP, without_iso=True
    )

    rendered = list(resumed.spec.render())
    assert resumed.medium is None
    assert not any("media=cdrom" in item for item in rendered)
    assert "order=d" not in rendered


def test_a_run_with_the_usb_bus_is_not_resumed(host: Host, tmp_path: Path) -> None:
    started(host, tmp_path, usb_bus=True)

    with pytest.raises(errors.Refusal) as raised:
        resuming.resume(
            host.ports, settings(tmp_path), host.root, RUN, stamp=STAMP, without_iso=False
        )

    assert raised.value.reason is refusals.RefusalReason.TOPOLOGY_INCONSISTENT
    assert not any("before-resume" in path for path in host.files.writes)


def test_a_running_machine_blocks_the_resumption(host: Host, tmp_path: Path) -> None:
    prepared = started(host, tmp_path)
    launching.launch(
        host.ports, root=host.root, spec=prepared.spec, run=RUN,
        run_directory=prepared.run_directory,
    )

    with pytest.raises(errors.Refusal) as raised:
        resuming.resume(
            host.ports, settings(tmp_path), host.root, RUN, stamp=STAMP, without_iso=False
        )

    assert raised.value.reason is refusals.RefusalReason.MACHINE_RUNNING


def test_a_run_this_tree_did_not_start_is_refused(host: Host, tmp_path: Path) -> None:
    host.run_directory.path.mkdir(parents=True)

    with pytest.raises(errors.Refusal) as raised:
        resuming.resume(
            host.ports, settings(tmp_path), host.root, RUN, stamp=STAMP, without_iso=False
        )

    assert raised.value.reason is refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE


def test_prepare_leaves_the_record_the_resumption_reads(host: Host, tmp_path: Path) -> None:
    prepared = started(host, tmp_path, extra_disks=(host.root.path / "other.qcow2",))

    record = json.loads(host.files.read_bytes(
        safepaths.SafePath(prepared.run_directory.path / defaults.RUN_RECORD_NAME), limit=1 << 20
    ))

    assert record["disk"] == {
        "source": str(host.root.path / "target.qcow2"),
        "overlay": str(prepared.run_directory.path / "disk.qcow2"),
    }
    assert [item["overlay"] for item in record["extras"]] == [
        str(prepared.run_directory.path / "other-1.qcow2")
    ]
    assert record["iso"] is None and record["usb_bus"] is False and record["run"] == str(RUN)

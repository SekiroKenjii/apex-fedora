"""A test machine runs over fresh overlays in its own run directory, with the image it boots."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from machinehost import RUN, Host

from apex.adapters.fakes import fake_process
from apex.config import defaults, loader
from apex.kernel import errors, quantities, refusals, safepaths
from apex.model import machines
from apex.provisioning import testspec

PRIVATE = quantities.FileMode(0o600)


class ImageTool(fake_process.ScriptedProcess):
    """Answers qemu-img and creates the overlay it was asked for, so the chain can be walked."""

    def __init__(self, host: Host) -> None:
        super().__init__()
        self.host = host

    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        if vector[:2] == ("qemu-img", "info"):
            self.expect(vector, fake_process.Reply(stdout=json.dumps({"format": "qcow2"}).encode()))
        elif vector[:2] == ("qemu-img", "create"):
            overlay = Path(vector[-1])
            overlay.parent.mkdir(parents=True, exist_ok=True)
            overlay.write_bytes(b"")
            self.expect(vector, fake_process.Reply())
        return super().run(argv, **keywords)


def settings(tmp_path: Path) -> loader.Settings:
    for name in ("OVMF_CODE.fd", "OVMF_VARS.fd"):
        (tmp_path / name).write_bytes(name.encode())
    host = tmp_path / "settings.toml"
    host.write_text(
        f'[builder]\nfirmware_code = "{tmp_path}/OVMF_CODE.fd"\n'
        f'firmware_variables = "{tmp_path}/OVMF_VARS.fd"\n'
    )
    return loader.load(host_file=host, environment={})


def prepared(host: Host, tmp_path: Path, request: testspec.TestRequest) -> testspec.Prepared:
    held = settings(tmp_path)
    host.files.write_atomic(
        safepaths.SafePath(held.builder.firmware_variables), b"vars", mode=PRIVATE
    )
    ports = dataclasses.replace(host.ports, processes=ImageTool(host))
    return testspec.prepare(ports, held, host.root, request, run=RUN)


def source(host: Host, name: str) -> Path:
    target = host.root.path / name
    target.write_bytes(b"")
    return target


def test_the_disk_and_extras_become_overlays_and_the_variables_are_copied_twice(
    host: Host, tmp_path: Path
) -> None:
    disk = source(host, "target.qcow2")
    other = source(host, "other.qcow2")

    found = prepared(host, tmp_path, testspec.TestRequest(disk=disk, extra_disks=(other,)))

    run_directory = host.root.path / "vm-runs" / str(RUN)
    assert found.run_directory.path == run_directory
    assert (run_directory / "disk.qcow2").is_file() and (run_directory / "other-1.qcow2").is_file()
    rendered = list(found.spec.render())
    assert f"if=virtio,format=qcow2,file={run_directory}/disk.qcow2" in rendered
    assert any("apex-other-1" in item and "other-1.qcow2" in item for item in rendered)
    assert f"if=pflash,format=raw,file={run_directory}/{defaults.VARIABLES_NAME}" in rendered
    for name in (defaults.VARIABLES_NAME, defaults.INITIAL_VARIABLES_NAME):
        assert str(run_directory / name) in host.files.writes
    assert found.spec.role is machines.VmRole.TEST and found.medium is None
    assert "-nic" in rendered and "none" in rendered


def test_an_image_to_boot_is_attached_as_a_cdrom_and_boots_first(
    host: Host, tmp_path: Path
) -> None:
    disk = source(host, "target.qcow2")
    iso = source(host, "apex-live.iso")

    found = prepared(
        host, tmp_path,
        testspec.TestRequest(disk=disk, iso=iso, medium=machines.Medium.LIVE, guest_ssh=True),
    )

    rendered = list(found.spec.render())
    assert f"file={iso},format=raw,media=cdrom,readonly=on" in rendered
    assert "order=d" in rendered
    assert any("hostfwd=tcp:127.0.0.1:22245-:22" in item for item in rendered)
    assert found.medium is machines.Medium.LIVE


def test_an_image_without_a_medium_or_a_medium_without_an_image_is_refused(host: Host) -> None:
    disk = source(host, "target.qcow2")
    iso = source(host, "apex.iso")

    for request in (
        lambda: testspec.TestRequest(disk=disk, iso=iso),
        lambda: testspec.TestRequest(disk=disk, medium=machines.Medium.LIVE),
    ):
        with pytest.raises(errors.Refusal) as raised:
            request()
        assert raised.value.reason is refusals.RefusalReason.TOPOLOGY_INCONSISTENT
    assert not (host.root.path / "vm-runs").exists()


def test_more_than_two_extra_disks_are_refused(host: Host) -> None:
    disk = source(host, "target.qcow2")
    extras = tuple(source(host, f"{name}.qcow2") for name in ("a", "b", "c"))

    with pytest.raises(errors.Refusal) as raised:
        testspec.TestRequest(disk=disk, extra_disks=extras)

    assert raised.value.reason is refusals.RefusalReason.TOO_MANY_DEVICES


def test_a_source_disk_outside_the_runtime_root_is_refused(host: Host, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.qcow2"
    outside.write_bytes(b"")

    with pytest.raises(errors.Refusal) as raised:
        prepared(host, tmp_path, testspec.TestRequest(disk=outside))

    assert raised.value.reason is refusals.RefusalReason.PATH_OUTSIDE_RUNTIME_ROOT

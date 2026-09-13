"""The machine command starts, looks at, stops and reclaims through the provisioning context."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import installerruns
import pytest
from storagefixtures import Storage

from apex.adapters.fakes import (
    fake_clock,
    fake_downloading,
    fake_files,
    fake_hypervisor,
    fake_process,
    fake_qmp,
)
from apex.adapters.real import real_files
from apex.cli import commandspecs
from apex.cli.commands import machine_command
from apex.config import loader
from apex.kernel import errors, identifiers, quantities, refusals, safepaths
from apex.ports import portset
from apex.verification import installerfault
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]


@pytest.fixture
def prepared(tmp_path: Path) -> tuple[loader.Settings, safepaths.RuntimeRoot]:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    for name in ("builder.qcow2", "seed.iso", "builder-vars.fd"):
        (base / name).write_bytes(b"")
    code = tmp_path / "OVMF_CODE.fd"
    code.write_bytes(b"")
    host = tmp_path / "settings.toml"
    host.write_text(f'[builder]\nfirmware_code = "{code}"\n')
    return loader.load(host_file=host, environment={}), safepaths.RuntimeRoot.adopt(base)


def bundle(ports: portset.HostPorts) -> portset.HostPorts:
    return dataclasses.replace(
        ports,
        files=fake_files.MemoryFiles(),
        hypervisor=fake_hypervisor.FakeQemu(),
        monitor=fake_qmp.ScriptedQmp({"system_powerdown": {}}),
        clock=fake_clock.ManualClock(),
    )


def request(
    ports: portset.HostPorts,
    settings: loader.Settings,
    root: safepaths.RuntimeRoot | None,
    *arguments: str,
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=settings,
            repository=safepaths.SourceRoot.adopt(REPOSITORY),
            root=root,
            environment={},
            bundle=lambda _root: ports,
        ),
    )


def test_status_says_nothing_runs_on_a_fresh_root(
    ports: portset.HostPorts, prepared: tuple[loader.Settings, safepaths.RuntimeRoot]
) -> None:
    settings, root = prepared

    reply = machine_command.run(request(bundle(ports), settings, root, "status"))

    assert reply.document == {"running": False, "lease": None}


def test_the_builder_starts_from_prepared_storage_and_the_lease_carries_the_witness(
    ports: portset.HostPorts, prepared: tuple[loader.Settings, safepaths.RuntimeRoot]
) -> None:
    settings, root = prepared
    held = bundle(ports)

    started = machine_command.run(request(held, settings, root, "start", "--role", "builder"))
    status = machine_command.run(request(held, settings, root, "status"))

    assert isinstance(started.document, dict)
    lease = started.document["started"]
    assert isinstance(lease, dict) and lease["intent"]["role"] == "builder"  # type: ignore[index]
    assert lease["intent"]["witness"] == "simulated"  # type: ignore[index]
    assert isinstance(status.document, dict) and status.document["running"] is True
    hypervisor = held.hypervisor
    assert isinstance(hypervisor, fake_hypervisor.FakeQemu)
    assert [item.spec.role.value for item in hypervisor.spawned] == ["builder"]


def test_stop_asks_the_machine_to_power_down_and_releases_the_lease(
    ports: portset.HostPorts, prepared: tuple[loader.Settings, safepaths.RuntimeRoot]
) -> None:
    settings, root = prepared
    held = bundle(ports)
    machine_command.run(request(held, settings, root, "start", "--role", "builder"))
    hypervisor = held.hypervisor
    assert isinstance(hypervisor, fake_hypervisor.FakeQemu)
    monitor = held.monitor
    assert isinstance(monitor, fake_qmp.ScriptedQmp)
    monitor.react("system_powerdown", lambda: hypervisor.exit(hypervisor.spawned[0].identity))

    stopped = machine_command.run(request(held, settings, root, "stop"))
    status = machine_command.run(request(held, settings, root, "status"))

    process = hypervisor.spawned[0].identity.process
    assert stopped.document == {"ending": "stopped", "process": process}
    assert isinstance(status.document, dict) and status.document["running"] is False


def test_stop_with_nothing_running_is_refused(
    ports: portset.HostPorts, prepared: tuple[loader.Settings, safepaths.RuntimeRoot]
) -> None:
    settings, root = prepared

    with pytest.raises(errors.Refusal) as raised:
        machine_command.run(request(bundle(ports), settings, root, "stop"))

    assert raised.value.reason is refusals.RefusalReason.MACHINE_NOT_RUNNING


def test_reclaim_reports_a_machine_that_died_behind_the_lease(
    ports: portset.HostPorts, prepared: tuple[loader.Settings, safepaths.RuntimeRoot]
) -> None:
    settings, root = prepared
    held = bundle(ports)
    machine_command.run(request(held, settings, root, "start", "--role", "builder"))
    hypervisor = held.hypervisor
    assert isinstance(hypervisor, fake_hypervisor.FakeQemu)
    hypervisor.exit(hypervisor.spawned[0].identity)

    reply = machine_command.run(request(held, settings, root, "reclaim"))

    assert isinstance(reply.document, dict) and reply.document["orphaned"] is True


def test_a_machine_needs_a_runtime_root(
    ports: portset.HostPorts, prepared: tuple[loader.Settings, safepaths.RuntimeRoot]
) -> None:
    settings, _ = prepared

    with pytest.raises(errors.PreconditionUnmet):
        machine_command.run(request(bundle(ports), settings, None, "status"))


class ImageTool(fake_process.ScriptedProcess):
    def run(self, argv: Any, **keywords: Any) -> Any:
        vector = tuple(str(item) for item in argv)
        if vector[:2] == ("qemu-img", "info"):
            self.expect(vector, fake_process.Reply(stdout=b'{"format": "qcow2"}'))
        elif vector[:2] == ("qemu-img", "create"):
            overlay = Path(vector[-1])
            overlay.parent.mkdir(parents=True, exist_ok=True)
            overlay.write_bytes(b"")
            self.expect(vector, fake_process.Reply())
        return super().run(argv, **keywords)


def test_a_test_machine_starts_over_overlays_with_the_medium_on_its_lease(
    ports: portset.HostPorts,
    prepared: tuple[loader.Settings, safepaths.RuntimeRoot],
    tmp_path: Path,
) -> None:
    settings, root = prepared
    (tmp_path / "OVMF_VARS.fd").write_bytes(b"vars")
    host = tmp_path / "settings.toml"
    host.write_text(
        f'[builder]\nfirmware_code = "{tmp_path}/OVMF_CODE.fd"\n'
        f'firmware_variables = "{tmp_path}/OVMF_VARS.fd"\n'
    )
    settings = loader.load(host_file=host, environment={})
    (root.path / "target.qcow2").write_bytes(b"")
    (root.path / "apex-live.iso").write_bytes(b"")
    held = dataclasses.replace(bundle(ports), processes=ImageTool())
    held.files.write_atomic(
        safepaths.SafePath(tmp_path / "OVMF_VARS.fd"), b"vars", mode=quantities.FileMode(0o600)
    )

    started = machine_command.run(request(
        held, settings, root, "start", "--role", "test",
        "--disk", str(root.path / "target.qcow2"), "--iso", str(root.path / "apex-live.iso"),
        "--medium", "live", "--guest-ssh",
    ))

    assert isinstance(started.document, dict)
    lease = started.document["started"]
    assert isinstance(lease, dict)
    assert lease["intent"]["role"] == "test"  # type: ignore[index]
    assert lease["intent"]["witness"] == "simulated"  # type: ignore[index]
    hypervisor = held.hypervisor
    assert isinstance(hypervisor, fake_hypervisor.FakeQemu)
    rendered = list(hypervisor.spawned[0].spec.render())
    assert any("vm-runs" in item and "disk.qcow2" in item for item in rendered)
    assert "order=d" in rendered


def test_a_test_machine_without_a_disk_is_refused(
    ports: portset.HostPorts, prepared: tuple[loader.Settings, safepaths.RuntimeRoot]
) -> None:
    settings, root = prepared

    with pytest.raises(errors.Refusal) as raised:
        machine_command.run(request(bundle(ports), settings, root, "start", "--role", "test"))

    assert raised.value.reason is refusals.RefusalReason.TOPOLOGY_INCONSISTENT


def test_prepare_makes_the_builders_storage_from_the_reviewed_base(
    ports: portset.HostPorts, tmp_path: Path
) -> None:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    root = safepaths.RuntimeRoot.adopt(base)
    (base / "builder-base.qcow2").write_bytes(b"stale bytes")
    for name in ("OVMF_CODE.fd", "OVMF_VARS.fd"):
        (tmp_path / name).write_bytes(name.encode())
    host = tmp_path / "settings.toml"
    host.write_text(
        f'[builder]\nfirmware_code = "{tmp_path}/OVMF_CODE.fd"\n'
        f'firmware_variables = "{tmp_path}/OVMF_VARS.fd"\n'
    )
    settings = loader.load(host_file=host, environment={})
    held = dataclasses.replace(
        bundle(ports),
        files=real_files.LocalFiles(),
        downloads=fake_downloading.PinningFetcher(),
        processes=Storage(),
    )

    reply = machine_command.run(request(held, settings, root, "prepare"))

    assert reply.document == {"prepared": {
        "base": str(base / "builder-base.qcow2"),
        "base_fetched": True,
        "disk_created": True,
        "key_created": True,
        "seed_created": True,
        "variables_copied": True,
    }}
    fetcher = held.downloads
    assert isinstance(fetcher, fake_downloading.PinningFetcher)
    assert str(fetcher.fetched[0][0]).endswith(".qcow2")
    assert (base / "seed.iso").read_bytes()[16 * 2048 + 40:16 * 2048 + 46] == b"cidata"
    assert (base / "builder-vars.fd").read_bytes() == b"OVMF_VARS.fd"


def test_a_test_machine_boots_an_image_as_usb_storage_over_the_emulated_bus(
    ports: portset.HostPorts,
    prepared: tuple[loader.Settings, safepaths.RuntimeRoot],
    tmp_path: Path,
) -> None:
    _, root = prepared
    settings = variables_settings(tmp_path)
    for name in ("target.qcow2", "other.qcow2", "ventoy.qcow2"):
        (root.path / name).write_bytes(b"")
    held = dataclasses.replace(bundle(ports), processes=Storage())
    held.files.write_atomic(
        safepaths.SafePath(tmp_path / "OVMF_VARS.fd"), b"vars", mode=quantities.FileMode(0o600)
    )

    started = machine_command.run(request(
        held, settings, root, "start", "--role", "test",
        "--disk", str(root.path / "target.qcow2"), "--extra-disk", str(root.path / "other.qcow2"),
        "--usb-bus", "--boot-usb", str(root.path / "ventoy.qcow2"),
    ))

    assert isinstance(started.document, dict)
    hypervisor = held.hypervisor
    assert isinstance(hypervisor, fake_hypervisor.FakeQemu)
    rendered = list(hypervisor.spawned[0].spec.render())
    assert "qemu-xhci,id=apex-usb" in rendered
    assert any("boot-usb.qcow2" in item for item in rendered)
    assert any(item.endswith("bootindex=1") for item in rendered)


def test_a_usb_fixture_is_hot_plugged_into_the_running_test_machine(
    ports: portset.HostPorts,
    prepared: tuple[loader.Settings, safepaths.RuntimeRoot],
    tmp_path: Path,
) -> None:
    _, root = prepared
    settings = variables_settings(tmp_path)
    for name in ("target.qcow2", "fixture.qcow2"):
        (root.path / name).write_bytes(b"")
    held = dataclasses.replace(bundle(ports), processes=Storage())
    held.files.write_atomic(
        safepaths.SafePath(tmp_path / "OVMF_VARS.fd"), b"vars", mode=quantities.FileMode(0o600)
    )
    monitor = held.monitor
    assert isinstance(monitor, fake_qmp.ScriptedQmp)
    monitor.reply("blockdev-add", {})
    monitor.reply("device_add", {})
    machine_command.run(request(
        held, settings, root, "start", "--role", "test",
        "--disk", str(root.path / "target.qcow2"), "--usb-bus",
    ))

    reply = machine_command.run(request(
        held, settings, root, "hotplug-usb", "--source", str(root.path / "fixture.qcow2")
    ))

    assert isinstance(reply.document, dict)
    attached = reply.document["attached"]
    assert isinstance(attached, dict) and attached["status"] == "ATTACHED"
    assert str(attached["overlay"]).endswith("/hotplug-usb.qcow2")
    assert [command.name for command in monitor.executed] == ["blockdev-add", "device_add"]


def variables_settings(tmp_path: Path) -> loader.Settings:
    (tmp_path / "OVMF_VARS.fd").write_bytes(b"vars")
    host = tmp_path / "settings.toml"
    host.write_text(
        f'[builder]\nfirmware_code = "{tmp_path}/OVMF_CODE.fd"\n'
        f'firmware_variables = "{tmp_path}/OVMF_VARS.fd"\n'
    )
    return loader.load(host_file=host, environment={})


def test_power_loss_kills_only_a_running_test_machine_and_records_the_fault(
    ports: portset.HostPorts,
    prepared: tuple[loader.Settings, safepaths.RuntimeRoot],
    tmp_path: Path,
) -> None:
    _, root = prepared
    settings = variables_settings(tmp_path)
    (root.path / "target.qcow2").write_bytes(b"")
    held = dataclasses.replace(bundle(ports), processes=Storage())
    held.files.write_atomic(
        safepaths.SafePath(tmp_path / "OVMF_VARS.fd"), b"vars", mode=quantities.FileMode(0o600)
    )
    machine_command.run(request(
        held, settings, root, "start", "--role", "test", "--disk", str(root.path / "target.qcow2"),
    ))

    reply = machine_command.run(request(held, settings, root, "power-loss"))
    status = machine_command.run(request(held, settings, root, "status"))

    assert isinstance(reply.document, dict)
    assert str(reply.document["record"]).endswith("/power-loss.json")
    assert isinstance(status.document, dict) and status.document["running"] is False
    hypervisor = held.hypervisor
    assert isinstance(hypervisor, fake_hypervisor.FakeQemu)
    assert reply.document["terminated"] == hypervisor.spawned[0].identity.process


def test_power_loss_is_refused_for_the_builder(
    ports: portset.HostPorts, prepared: tuple[loader.Settings, safepaths.RuntimeRoot]
) -> None:
    settings, root = prepared
    held = bundle(ports)
    machine_command.run(request(held, settings, root, "start", "--role", "builder"))

    with pytest.raises(errors.Refusal) as raised:
        machine_command.run(request(held, settings, root, "power-loss"))

    assert raised.value.reason is refusals.RefusalReason.NOT_A_DISPOSABLE_MACHINE


def started_test_run(
    ports: portset.HostPorts, tmp_path: Path, root: safepaths.RuntimeRoot
) -> tuple[portset.HostPorts, loader.Settings]:
    settings = variables_settings(tmp_path)
    for name in ("target.qcow2", "other.qcow2"):
        (root.path / name).write_bytes(b"")
    held = dataclasses.replace(bundle(ports), processes=Storage())
    held.files.write_atomic(
        safepaths.SafePath(tmp_path / "OVMF_VARS.fd"), b"vars", mode=quantities.FileMode(0o600)
    )
    machine_command.run(request(
        held, settings, root, "start", "--role", "test",
        "--disk", str(root.path / "target.qcow2"), "--extra-disk", str(root.path / "other.qcow2"),
    ))
    machine_command.run(request(held, settings, root, "power-loss"))
    return held, settings


def test_a_stopped_run_is_compared_against_its_sources_by_its_directory(
    ports: portset.HostPorts,
    prepared: tuple[loader.Settings, safepaths.RuntimeRoot],
    tmp_path: Path,
) -> None:
    _, root = prepared
    held, settings = started_test_run(ports, tmp_path, root)
    run_directory = next((root.path / "vm-runs").iterdir())
    tools = held.processes
    assert isinstance(tools, Storage)
    for overlay in ("disk.qcow2", "other-1.qcow2"):
        source = "target.qcow2" if overlay == "disk.qcow2" else "other.qcow2"
        tools.expect(
            ("qemu-img", "compare", "-f", "qcow2", "-F", "qcow2",
             str(root.path / source), str(run_directory / overlay)),
            fake_process.Reply(exit_code=0, stdout=b"Images are identical."),
        )

    reply = machine_command.run(
        request(held, settings, root, "compare", "--run", str(run_directory))
    )

    assert isinstance(reply.document, dict)
    disks = reply.document["disks"]
    assert isinstance(disks, list)
    assert [item["unchanged"] for item in disks] == [True, True]  # type: ignore[index]
    assert reply.document["firmware_variables_unchanged"] is True


def test_a_stopped_run_is_resumed_by_its_id_over_the_same_overlays(
    ports: portset.HostPorts,
    prepared: tuple[loader.Settings, safepaths.RuntimeRoot],
    tmp_path: Path,
) -> None:
    _, root = prepared
    held, settings = started_test_run(ports, tmp_path, root)
    run_directory = next((root.path / "vm-runs").iterdir())

    reply = machine_command.run(
        request(held, settings, root, "resume", "--run", run_directory.name)
    )
    status = machine_command.run(request(held, settings, root, "status"))

    assert isinstance(reply.document, dict)
    lease = reply.document["resumed"]
    assert isinstance(lease, dict) and lease["intent"]["run"] == run_directory.name  # type: ignore[index]
    assert isinstance(status.document, dict) and status.document["running"] is True
    hypervisor = held.hypervisor
    assert isinstance(hypervisor, fake_hypervisor.FakeQemu)
    assert len(hypervisor.spawned) == 2
    assert list(hypervisor.spawned[1].spec.render()) == list(hypervisor.spawned[0].spec.render())


def finished_fault_run(
    ports: portset.HostPorts,
    tmp_path: Path,
    root: safepaths.RuntimeRoot,
    *,
    guest: dict[str, object] | None = None,
) -> tuple[portset.HostPorts, loader.Settings, Path]:
    """An installer machine started, faulted and powered off, its records beside the run."""
    settings = variables_settings(tmp_path)
    for name in ("target.qcow2", "other.qcow2"):
        (root.path / name).write_bytes(b"")
    iso = root.path / installerruns.ISO_NAME
    iso.write_bytes(installerruns.ISO_BYTES)
    held = dataclasses.replace(bundle(ports), processes=Storage())
    held.files.write_atomic(
        safepaths.SafePath(tmp_path / "OVMF_VARS.fd"), b"vars", mode=quantities.FileMode(0o600)
    )
    machine_command.run(request(
        held, settings, root, "start", "--role", "test",
        "--disk", str(root.path / "target.qcow2"), "--extra-disk", str(root.path / "other.qcow2"),
        "--iso", str(iso), "--medium", "installer", "--serial-console",
    ))
    run_directory = next((root.path / "vm-runs").iterdir())
    held_run = safepaths.SafePath(run_directory)
    asked = installerfault.Request(
        case=installerruns.CASE,
        image=held.digests.file(safepaths.SafePath.regular_file(iso, within=root)),
        process=4242,
        run=identifiers.RunId.parse(run_directory.name),
    )
    installerfault.write_request(held, held_run, asked)
    installerfault.write_kept(
        held, held_run, request=asked,
        observations=installerruns.confirming() if guest is None else guest,  # type: ignore[arg-type]
    )
    machine_command.run(request(held, settings, root, "power-loss"))
    return held, settings, run_directory


def expect_comparisons(
    held: portset.HostPorts, root: safepaths.RuntimeRoot, run_directory: Path, *exits: int
) -> None:
    tools = held.processes
    assert isinstance(tools, Storage)
    for overlay, exit_code in zip(("disk.qcow2", "other-1.qcow2"), exits, strict=True):
        source = "target.qcow2" if overlay == "disk.qcow2" else "other.qcow2"
        tools.expect(
            ("qemu-img", "compare", "-f", "qcow2", "-F", "qcow2",
             str(root.path / source), str(run_directory / overlay)),
            fake_process.Reply(
                exit_code=exit_code,
                stdout=b"Images are identical." if exit_code == 0 else b"Content mismatch",
            ),
        )


def test_a_finished_fault_run_is_collected_into_its_result_once_both_disks_prove_unchanged(
    ports: portset.HostPorts,
    prepared: tuple[loader.Settings, safepaths.RuntimeRoot],
    tmp_path: Path,
) -> None:
    _, root = prepared
    held, settings, run_directory = finished_fault_run(ports, tmp_path, root)
    expect_comparisons(held, root, run_directory, 0, 0)

    reply = machine_command.run(
        request(held, settings, root, "collect", "--run", str(run_directory))
    )

    assert isinstance(reply.document, dict) and reply.exit_code == 0
    assert reply.document["status"] == "PASS" and reply.document["case"] == installerruns.CASE
    proof = str(reply.document["proof"])
    assert proof == str(run_directory / "fault-result.json")
    assert held.files.exists(safepaths.SafePath(Path(proof)))


def test_a_disk_that_changed_leaves_a_failed_result_and_is_refused(
    ports: portset.HostPorts,
    prepared: tuple[loader.Settings, safepaths.RuntimeRoot],
    tmp_path: Path,
) -> None:
    _, root = prepared
    held, settings, run_directory = finished_fault_run(ports, tmp_path, root)
    expect_comparisons(held, root, run_directory, 0, 1)

    with pytest.raises(errors.Refusal) as refused:
        machine_command.run(request(held, settings, root, "collect", "--run", str(run_directory)))

    assert refused.value.reason is refusals.RefusalReason.FAULT_DISK_CHANGED
    assert held.files.exists(safepaths.SafePath(run_directory / "fault-result.json"))


def test_a_report_that_does_not_confirm_the_rejection_is_not_collected(
    ports: portset.HostPorts,
    prepared: tuple[loader.Settings, safepaths.RuntimeRoot],
    tmp_path: Path,
) -> None:
    _, root = prepared
    held, settings, run_directory = finished_fault_run(
        ports, tmp_path, root, guest={**installerruns.confirming(), "selinux_after": "Permissive"}
    )
    expect_comparisons(held, root, run_directory, 0, 0)

    with pytest.raises(errors.Refusal) as refused:
        machine_command.run(request(held, settings, root, "collect", "--run", str(run_directory)))

    assert refused.value.reason is refusals.RefusalReason.FAULT_NOT_CONFIRMED
    assert not held.files.exists(safepaths.SafePath(run_directory / "fault-result.json"))

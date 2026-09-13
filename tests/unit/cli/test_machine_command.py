"""The machine command starts, looks at, stops and reclaims through the provisioning context."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import fake_clock, fake_files, fake_hypervisor, fake_process, fake_qmp
from apex.cli import commandspecs
from apex.cli.commands import machine_command
from apex.config import loader
from apex.kernel import errors, quantities, refusals, safepaths
from apex.ports import portset
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

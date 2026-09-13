"""The verify command takes everything from the runtime root and runs the recipe end to end."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from answeringguest import AnsweringGuest

from apex.adapters.fakes import fake_clock, fake_files, fake_hypervisor, fake_qmp
from apex.cli import commandspecs
from apex.cli.commands import verify_command
from apex.config import defaults, loader
from apex.kernel import claims, errors, refusals, safepaths
from apex.model import machines
from apex.ports import portset
from apex.provisioning import launching
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]
CANDIDATE = "sha256:" + "c" * 64


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / defaults.GUEST_KEY_NAME).write_bytes(b"key")
    (base / defaults.AGENT_WHEEL_NAME).write_bytes(b"wheel")
    (base / "candidate.json").write_text(json.dumps({"digest": CANDIDATE, "build_id": "b" * 32}))
    for name in ("disk.qcow2", "code.fd", "vars.fd"):
        (base / name).write_bytes(b"")
    return safepaths.RuntimeRoot.adopt(base)


def bundle(ports: portset.HostPorts, guest: AnsweringGuest) -> portset.HostPorts:
    return dataclasses.replace(
        ports,
        files=fake_files.MemoryFiles(),
        hypervisor=fake_hypervisor.FakeQemu(),
        monitor=fake_qmp.ScriptedQmp({"system_powerdown": {}}),
        clock=fake_clock.ManualClock(),
        guest=guest,
    )


def spec(root: safepaths.RuntimeRoot, role: machines.VmRole) -> machines.VmSpec:
    present = lambda name: safepaths.SafePath.regular_file(root.path / name, within=root)  # noqa: E731
    return machines.VmSpec.build(
        role=role,
        resources=machines.VmResources(memory=defaults.TEST_MACHINE.memory, processors=2),
        root_disk=present("disk.qcow2"),
        firmware=machines.Firmware(code=present("code.fd"), variables=present("vars.fd")),
        monitor=machines.MonitorSocket(root.child("qmp.sock")),
        serial=machines.SerialFile(root.child("serial.log")),
    )


def running(ports: portset.HostPorts, root: safepaths.RuntimeRoot, role: machines.VmRole) -> None:
    """Launch under a hypervisor that declares itself real, so the lease carries a witness."""
    declared_real = type("RealQemu", (fake_hypervisor.FakeQemu,), {
        "environment": claims.EnvironmentKind.BUILD
    })
    launcher = dataclasses.replace(ports, hypervisor=declared_real())
    run = launcher.identities.run_id()
    launching.launch(
        launcher, root=root, spec=spec(root, role), run=run,
        run_directory=root.child(f"vm-runs/{run}"), medium=machines.Medium.LIVE,
    )
    hypervisor = ports.hypervisor
    assert isinstance(hypervisor, fake_hypervisor.FakeQemu)
    hypervisor.spawned.extend(launcher.hypervisor.spawned)  # type: ignore[attr-defined]
    for spawned in launcher.hypervisor.spawned:  # type: ignore[attr-defined]
        hypervisor._alive[spawned.identity.process] = spawned.identity  # noqa: SLF001


def request(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, *arguments: str
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=loader.load(host_file=None, environment={}),
            repository=safepaths.SourceRoot.adopt(REPOSITORY),
            root=root,
            environment={},
            bundle=lambda _root: ports,
        ),
    )


def test_the_live_recipe_runs_against_the_leased_guest_and_the_fake_bundle_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({
        "fault.live-write-denial": {"status": "PASS"},
        "fault.usb-write-denial": {"status": "PASS"},
    })
    held = bundle(ports, guest)
    running(held, root, machines.VmRole.TEST)

    reply = verify_command.run(request(held, root, "live-protection", "--user", "tester"))

    assert isinstance(reply.document, dict)
    assert reply.document["succeeded"] is False
    assert reply.document["refusal"] == "evidence.simulated-environment"
    assert reply.document["not_tested"] == ["live.disk-protection"]
    assert reply.exit_code == errors.Refusal.exit_code
    assert guest.asked == ["fault.live-write-denial", "fault.usb-write-denial"]
    lease = launching.current(held, root=root)
    assert lease is not None and lease.intent.witness is claims.EnvironmentKind.LIVE_VM
    assert guest.targets[-1].user == "tester" and guest.targets[-1].port.value == 22245
    assert [str(item.remote) for item in guest.sent][-1].endswith(defaults.AGENT_WHEEL_NAME)


def test_without_a_running_machine_the_recipe_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))

    with pytest.raises(errors.Refusal) as raised:
        verify_command.run(request(held, root, "live-protection", "--user", "tester"))

    assert raised.value.reason is refusals.RefusalReason.MACHINE_NOT_RUNNING


def test_a_builder_is_never_a_verification_target(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    running(held, root, machines.VmRole.BUILDER)

    with pytest.raises(errors.Refusal) as raised:
        verify_command.run(request(held, root, "desktop-theme", "--user", "tester"))

    assert raised.value.reason is refusals.RefusalReason.NOT_A_DISPOSABLE_MACHINE


@pytest.mark.parametrize("missing", [defaults.AGENT_WHEEL_NAME, "candidate.json"])
def test_a_missing_wheel_or_candidate_is_an_unmet_precondition(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, missing: str
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    running(held, root, machines.VmRole.TEST)
    (root.path / missing).unlink()

    with pytest.raises(errors.PreconditionUnmet):
        verify_command.run(request(held, root, "live-protection", "--user", "tester"))


def test_a_machine_launched_by_a_fake_is_refused_before_the_guest_is_touched(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"fault.live-write-denial": {"status": "PASS"}})
    held = bundle(ports, guest)
    run = held.identities.run_id()
    launching.launch(
        held, root=root, spec=spec(root, machines.VmRole.TEST), run=run,
        run_directory=root.child(f"vm-runs/{run}"), medium=machines.Medium.LIVE,
    )

    reply = verify_command.run(request(held, root, "live-protection", "--user", "tester"))

    assert isinstance(reply.document, dict)
    assert reply.document["refusal"] == "evidence.environment-not-witnessed"
    assert guest.asked == [] and guest.sent == []

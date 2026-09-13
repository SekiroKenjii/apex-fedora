"""The verify command takes everything from the runtime root and runs the recipe end to end."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import parentbuild
import pytest
from answeringguest import AnsweringGuest
from monitorfixtures import DrawingMonitor

from apex.adapters.fakes import (
    fake_clock,
    fake_downloading,
    fake_files,
    fake_hypervisor,
    fake_qmp,
)
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
HEADER = b"P6\n300 100\n255\n"
BARS = HEADER + (b"\xe6\x26\x26" * 100 + b"\x26\xbf\x40" * 100 + b"\x26\x4c\xe6" * 100) * 100


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


def credentials(
    held: portset.HostPorts, root: safepaths.RuntimeRoot, user: str = "apex-test"
) -> Path:
    """The fixture's credentials, on disk for the path check and in the fake files for reading."""
    directory = root.path / defaults.TEST_ACCESS_DIRECTORY
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / defaults.CREDENTIALS_NAME
    payload = json.dumps({"user": user, "password": "Ab-1_", "key": "k"}).encode()
    path.write_bytes(payload)
    held.files.write_atomic(safepaths.SafePath(path), payload, mode=defaults.RECORD_MODE)
    return path


def test_the_render_recipe_logs_in_with_the_credentials_and_the_fake_bundle_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({
        "desktop.session": [{"found": False}, {"found": True, "wayland": True}],
        "desktop.greeter": {"found": True},
        "desktop.shell-startup": {"found": True, "pid": 1, "event": {}},
        "desktop.overview": [{"reached": True}, {"reached": True}, {"reached": True}],
        "desktop.render": {"presented": True, "display_type": "GdkWaylandDisplay"},
    })
    held = bundle(ports, guest)
    assert isinstance(held.files, fake_files.MemoryFiles)
    held = dataclasses.replace(held, monitor=DrawingMonitor(held.files, {"application.ppm": BARS}))
    running(held, root, machines.VmRole.TEST)
    path = credentials(held, root)

    reply = verify_command.run(request(held, root, "desktop-render", "--credentials", str(path)))

    assert isinstance(reply.document, dict)
    assert reply.document["refusal"] == "evidence.simulated-environment"
    assert reply.document["not_tested"] == ["desktop.password-wayland"]
    assert guest.asked[:3] == ["desktop.session", "desktop.greeter", "desktop.session"]
    assert guest.targets[-1].user == "apex-test"
    assert "Ab-1_" not in json.dumps(reply.document)


def test_the_render_recipe_needs_the_credentials(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    running(held, root, machines.VmRole.TEST)

    with pytest.raises(errors.Refusal) as raised:
        verify_command.run(request(held, root, "desktop-render", "--user", "tester"))

    assert raised.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_a_user_that_contradicts_the_credentials_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    running(held, root, machines.VmRole.TEST)
    path = credentials(held, root)

    with pytest.raises(errors.Refusal) as raised:
        verify_command.run(
            request(held, root, "desktop-render", "--user", "other", "--credentials", str(path))
        )

    assert raised.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert "other" in str(raised.value)


def test_without_an_account_from_either_source_the_recipe_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    running(held, root, machines.VmRole.TEST)

    with pytest.raises(errors.Refusal) as raised:
        verify_command.run(request(held, root, "live-protection"))

    assert raised.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_the_fingerprint_recipe_runs_in_the_builder_and_the_fake_bundle_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({
        "build.import-payload": {"tag": "localhost/apex-payload:x"},
        "fault.fingerprint-cleanup": {"status": "PASS"},
    })
    held = dataclasses.replace(bundle(ports, guest), downloads=fake_downloading.PinningFetcher())
    running(held, root, machines.VmRole.BUILDER)
    (root.path / defaults.BUILDER_KEY_NAME).write_bytes(b"key")
    parentbuild.documents(held.files, root)

    reply = verify_command.run(
        request(held, root, "fingerprint-cleanup", "--build", str(parentbuild.PARENT))
    )

    assert isinstance(reply.document, dict)
    assert reply.document["refusal"] == "evidence.simulated-environment"
    assert reply.document["not_tested"] == ["fingerprint.virtual-cleanup"]
    assert guest.asked == ["build.import-payload", "fault.fingerprint-cleanup"]
    assert guest.targets[-1].user == "builder" and guest.targets[-1].port.value == 22244
    assert str(guest.targets[-1].key).endswith(defaults.BUILDER_KEY_NAME)


def test_the_fingerprint_recipe_needs_the_build_it_tests(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    running(held, root, machines.VmRole.BUILDER)
    (root.path / defaults.BUILDER_KEY_NAME).write_bytes(b"key")

    with pytest.raises(errors.Refusal) as raised:
        verify_command.run(request(held, root, "fingerprint-cleanup"))

    assert raised.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_a_builder_recipe_takes_no_account_of_its_own(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    running(held, root, machines.VmRole.BUILDER)

    with pytest.raises(errors.Refusal) as raised:
        verify_command.run(
            request(held, root, "fingerprint-cleanup", "--user", "builder", "--build", "d" * 32)
        )

    assert raised.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_a_test_machine_is_not_the_builder_a_builder_recipe_needs(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    running(held, root, machines.VmRole.TEST)

    with pytest.raises(errors.Refusal) as raised:
        verify_command.run(request(held, root, "fingerprint-cleanup", "--build", "d" * 32))

    assert raised.value.reason is refusals.RefusalReason.MACHINE_ROLE_MISMATCH


def test_the_installer_trust_recipe_keeps_its_report_and_mints_nothing(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"fault.installer-trust": {"status": "PASS"}})
    held = bundle(ports, guest)
    running(held, root, machines.VmRole.BUILDER)
    (root.path / defaults.BUILDER_KEY_NAME).write_bytes(b"key")

    reply = verify_command.run(request(held, root, "installer-trust"))

    assert isinstance(reply.document, dict)
    assert reply.document["succeeded"] is True and reply.exit_code == 0
    assert reply.document["attested"] == [] and reply.document["not_tested"] == []
    assert "retained.fault.installer-trust" in reply.document["facts"]  # type: ignore[operator]
    assert guest.asked == ["fault.installer-trust"]

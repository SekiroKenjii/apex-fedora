"""The verify command takes everything from the runtime root and runs the recipe end to end."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import installerruns
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
from apex.verification import installerfault
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


def spec(
    root: safepaths.RuntimeRoot, role: machines.VmRole, *, serial_console: bool = False
) -> machines.VmSpec:
    present = lambda name: safepaths.SafePath.regular_file(root.path / name, within=root)  # noqa: E731
    serial: machines.Serial = machines.SerialFile(root.child("serial.log"))
    if serial_console:
        serial = machines.SerialSocket(
            root.child(defaults.SERIAL_SOCKET_NAME), log=root.child("serial.log")
        )
    return machines.VmSpec.build(
        role=role,
        resources=machines.VmResources(memory=defaults.TEST_MACHINE.memory, processors=2),
        root_disk=present("disk.qcow2"),
        firmware=machines.Firmware(code=present("code.fd"), variables=present("vars.fd")),
        monitor=machines.MonitorSocket(root.child("qmp.sock")),
        serial=serial,
    )


def running(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    role: machines.VmRole,
    *,
    serial_console: bool = False,
) -> None:
    """Launch under a hypervisor that declares itself real, so the lease carries a witness."""
    declared_real = type("RealQemu", (fake_hypervisor.FakeQemu,), {
        "environment": claims.EnvironmentKind.BUILD
    })
    launcher = dataclasses.replace(ports, hypervisor=declared_real())
    run = launcher.identities.run_id()
    launching.launch(
        launcher, root=root, spec=spec(root, role, serial_console=serial_console), run=run,
        run_directory=root.child(f"vm-runs/{run}"), medium=machines.Medium.LIVE,
    )
    hypervisor = ports.hypervisor
    assert isinstance(hypervisor, fake_hypervisor.FakeQemu)
    hypervisor.spawned.extend(launcher.hypervisor.spawned)  # type: ignore[attr-defined]
    for spawned in launcher.hypervisor.spawned:  # type: ignore[attr-defined]
        hypervisor._alive[spawned.identity.process] = spawned.identity  # noqa: SLF001


def request(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    *arguments: str,
    serial: contexts.SerialShell = contexts.unwired_serial,
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=loader.load(host_file=None, environment={}),
            repository=safepaths.SourceRoot.adopt(REPOSITORY),
            root=root,
            environment={},
            bundle=lambda _root: ports,
            serial=serial,
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
    key = directory / defaults.TEST_KEY_NAME
    key.write_bytes(b"test key")
    path = directory / defaults.CREDENTIALS_NAME
    payload = json.dumps({"user": user, "password": "Ab-1_", "key": str(key)}).encode()
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
    assert guest.targets[-1].key.path == path.with_name(defaults.TEST_KEY_NAME)
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


class Consoles:
    """A serial factory that hands out one answering guest and remembers what it was asked."""

    def __init__(self, guest: AnsweringGuest) -> None:
        self.guest = guest
        self.opened: list[tuple[safepaths.SafePath, int]] = []

    def __call__(self, socket_path: safepaths.SafePath, process: int) -> AnsweringGuest:
        self.opened.append((socket_path, process))
        return self.guest


def test_a_live_check_over_serial_reaches_the_rescue_shell_as_root_and_keeps_the_answer(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    over_ssh = AnsweringGuest({})
    held = bundle(ports, over_ssh)
    running(held, root, machines.VmRole.TEST, serial_console=True)
    consoles = Consoles(AnsweringGuest({"live.observe": {"cmdline": "rd.live.image"}}))

    reply = verify_command.run(request(held, root, "observe", "--serial", serial=consoles))

    assert isinstance(reply.document, dict)
    assert reply.document["succeeded"] is True and reply.exit_code == 0
    assert "retained.live.observe" in reply.document["facts"]  # type: ignore[operator]
    lease = launching.current(held, root=root)
    assert lease is not None
    assert consoles.opened == [(root.child(defaults.SERIAL_SOCKET_NAME), lease.identity.process)]
    assert consoles.guest.asked == ["live.observe"]
    assert consoles.guest.targets[-1].user == "root"
    assert over_ssh.asked == [] and over_ssh.runs == []


def test_the_older_case_names_spell_the_recipes_that_took_them_over(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    running(held, root, machines.VmRole.TEST, serial_console=True)
    consoles = Consoles(AnsweringGuest({
        "fault.live-lock": {"status": "PASS"},
        "fault.live-write-denial": {"status": "PASS"},
        "fault.usb-write-denial": {"status": "PASS"},
    }))

    lock = verify_command.run(request(held, root, "lock-fault", "--serial", serial=consoles))
    denial = verify_command.run(
        request(held, root, "write-denial", "--serial", "--user", "liveuser", serial=consoles)
    )

    assert isinstance(lock.document, dict) and lock.document["succeeded"] is True
    assert isinstance(denial.document, dict)
    assert denial.narrative.startswith("live-protection:")
    assert denial.document["not_tested"] == ["live.disk-protection"]
    assert consoles.guest.asked == [
        "fault.live-lock", "fault.live-write-denial", "fault.usb-write-denial"
    ]
    assert [target.user for target in consoles.guest.targets][-1] == "liveuser"


def test_serial_needs_a_machine_started_with_its_console(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    running(held, root, machines.VmRole.TEST)
    consoles = Consoles(AnsweringGuest({"live.observe": {}}))

    with pytest.raises(errors.Refusal) as caught:
        verify_command.run(request(held, root, "live-observe", "--serial", serial=consoles))

    assert caught.value.reason is refusals.RefusalReason.SERIAL_CONSOLE_ABSENT
    assert consoles.opened == []


def test_a_context_without_a_serial_shell_wired_cannot_verify_over_serial(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    running(held, root, machines.VmRole.TEST, serial_console=True)

    with pytest.raises(errors.PreconditionUnmet) as caught:
        verify_command.run(request(held, root, "live-observe", "--serial"))

    assert caught.value.reason is refusals.RefusalReason.TOPOLOGY_INCONSISTENT


def test_serial_takes_no_credentials_and_no_builder_recipe(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    running(held, root, machines.VmRole.TEST, serial_console=True)
    consoles = Consoles(AnsweringGuest({}))

    with pytest.raises(errors.Refusal) as with_credentials:
        verify_command.run(request(
            held, root, "live-observe", "--serial", "--credentials", "creds.json",
            serial=consoles,
        ))
    with pytest.raises(errors.Refusal) as builder:
        verify_command.run(request(held, root, "installer-trust", "--serial", serial=consoles))

    assert with_credentials.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert "--credentials" in str(with_credentials.value)
    assert builder.value.reason is refusals.RefusalReason.MACHINE_ROLE_MISMATCH
    assert consoles.opened == []


def test_the_live_observe_recipe_goes_over_ssh_without_serial(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"ventoy.observe": {"ventoy": True}})
    held = bundle(ports, guest)
    running(held, root, machines.VmRole.TEST)

    reply = verify_command.run(request(held, root, "ventoy-observe", "--user", "liveuser"))

    assert isinstance(reply.document, dict) and reply.document["succeeded"] is True
    assert guest.asked == ["ventoy.observe"] and guest.targets[-1].user == "liveuser"


def installer_run(
    held: portset.HostPorts, root: safepaths.RuntimeRoot, **shape: object
) -> tuple[safepaths.SafePath, int]:
    """A leased installer machine over a serial console, with the record the fault reads."""
    running(held, root, machines.VmRole.TEST, serial_console=True)
    lease = launching.current(held, root=root)
    assert lease is not None
    installerruns.record(held, root, lease.intent.run_directory, **shape)  # type: ignore[arg-type]
    return lease.intent.run_directory, lease.identity.process


def test_the_payload_fault_runs_over_serial_with_its_case_and_leaves_the_records(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    run_directory, process = installer_run(held, root)
    consoles = Consoles(AnsweringGuest({"fault.installer-payload": installerruns.confirming()}))

    reply = verify_command.run(request(
        held, root, "installer-payload", "--case", installerruns.CASE, "--serial", serial=consoles
    ))

    assert isinstance(reply.document, dict)
    assert reply.document["succeeded"] is True and reply.exit_code == 0
    assert consoles.guest.asked == ["fault.installer-payload"]
    assert consoles.guest.requests[0]["arguments"] == {
        "case": installerruns.CASE, "wrong_public_key": "",
    }
    request_file = installerfault.read_request(held, run_directory)
    assert request_file.case == installerruns.CASE and request_file.process == process
    assert held.files.exists(safepaths.SafePath(run_directory.path / defaults.FAULT_GUEST_NAME))
    assert "retained.fault.installer-payload" in reply.document["facts"]  # type: ignore[operator]


def test_the_payload_fault_needs_its_case_and_a_second_attempt_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    installer_run(held, root)
    consoles = Consoles(AnsweringGuest({"fault.installer-payload": installerruns.confirming()}))

    with pytest.raises(errors.Refusal) as unnamed:
        verify_command.run(request(held, root, "installer-payload", "--serial", serial=consoles))
    first = verify_command.run(request(
        held, root, "installer-payload", "--case", installerruns.CASE, "--serial", serial=consoles
    ))
    again = verify_command.run(request(
        held, root, "installer-payload", "--case", installerruns.CASE, "--serial", serial=consoles
    ))

    assert unnamed.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert isinstance(first.document, dict) and first.document["succeeded"] is True
    assert isinstance(again.document, dict)
    assert again.document["refusal"] == "fault.already-attempted"
    assert again.exit_code == errors.Refusal.exit_code
    assert consoles.guest.asked == ["fault.installer-payload"]


def test_the_wrong_key_case_reads_a_public_key_from_the_root_and_only_that_case_takes_one(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    installer_run(held, root)
    pem = b"-----BEGIN PUBLIC KEY-----\nsynthetic fixture\n"
    public = root.path / "wrong.pub"
    public.write_bytes(pem)
    held.files.write_atomic(safepaths.SafePath(public), pem, mode=defaults.RECORD_MODE)
    certificate = root.path / "wrong.crt"
    certificate.write_bytes(b"")
    held.files.write_atomic(
        safepaths.SafePath(certificate), b"-----BEGIN CERTIFICATE-----\nnot a key\n",
        mode=defaults.RECORD_MODE,
    )
    consoles = Consoles(AnsweringGuest({
        "fault.installer-payload": installerruns.confirming("wrong-key"),
    }))

    with pytest.raises(errors.Refusal) as not_a_key:
        verify_command.run(request(
            held, root, "installer-payload", "--case", "wrong-key", "--wrong-key",
            str(certificate), "--serial", serial=consoles,
        ))
    with pytest.raises(errors.Refusal) as unpaired:
        verify_command.run(request(
            held, root, "installer-payload", "--case", "corrupt-blob", "--wrong-key", str(public),
            "--serial", serial=consoles,
        ))
    with pytest.raises(errors.Refusal) as stray:
        verify_command.run(request(
            held, root, "live-observe", "--case", "corrupt-blob", "--serial", serial=consoles
        ))
    reply = verify_command.run(request(
        held, root, "installer-payload", "--case", "wrong-key", "--wrong-key", str(public),
        "--serial", serial=consoles,
    ))

    assert not_a_key.value.reason is refusals.RefusalReason.PUBLIC_KEY_MALFORMED
    assert unpaired.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert stray.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert isinstance(reply.document, dict) and reply.document["succeeded"] is True
    assert consoles.guest.requests[0]["arguments"] == {
        "case": "wrong-key", "wrong_public_key": pem.decode(),
    }


def test_the_diagnostics_come_home_in_one_step_and_an_incomplete_log_is_the_run_s_failure(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))
    installer_run(held, root)
    truncated = installerruns.whole_log(b"partial")
    truncated["truncated"] = True
    consoles = Consoles(AnsweringGuest({"installer.diagnostics": [
        installerruns.diagnostics(),
        installerruns.diagnostics(**{"anaconda.log": truncated}),
    ]}))

    asked = request(held, root, "installer-diagnostics", "--serial", serial=consoles)
    whole = verify_command.run(asked)
    partial = verify_command.run(asked)

    assert isinstance(whole.document, dict) and whole.document["succeeded"] is True
    assert "installer.logs-complete" in whole.document["facts"]  # type: ignore[operator]
    assert isinstance(partial.document, dict) and partial.document["succeeded"] is False
    assert partial.narrative.startswith(
        "installer-diagnostics: installer.logs: anaconda.log truncated"
    )
    assert consoles.guest.asked == ["installer.diagnostics", "installer.diagnostics"]


@pytest.mark.parametrize("recipe", ["fingerprint-rpms", "fingerprint-gtk"])
def test_the_fingerprint_package_tests_need_the_package_build_and_run_in_the_builder(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, recipe: str
) -> None:
    guest = AnsweringGuest({})
    held = bundle(ports, guest)
    running(held, root, machines.VmRole.BUILDER)
    (root.path / defaults.BUILDER_KEY_NAME).write_bytes(b"key")

    with pytest.raises(errors.Refusal) as unnamed:
        verify_command.run(request(held, root, recipe))
    reply = verify_command.run(request(held, root, recipe, "--build", "1" * 32))

    assert unnamed.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert isinstance(reply.document, dict) and reply.document["succeeded"] is False
    assert reply.document["refusal"] in {
        str(refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE),
        str(refusals.RefusalReason.STAGE_FAILED),
    }
    assert "1" * 32 in reply.narrative and guest.asked == []

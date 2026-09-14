"""The build command seeds the composition's recipes from the operator's choice and the lease."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import posixpath
import shutil
from pathlib import Path
from typing import Any

import nvidialockfixture as nvidia
import pytest
from answeringguest import AnsweringGuest
from parentbuild import PARENT, documents

from apex.adapters.fakes import (
    fake_clock,
    fake_downloading,
    fake_files,
    fake_guestshell,
    fake_hypervisor,
    fake_qmp,
)
from apex.cli import commandspecs
from apex.cli.commands import build_command
from apex.composition import exports
from apex.config import defaults, loader
from apex.kernel import claims, errors, refusals, safepaths
from apex.model import machines
from apex.ports import portset
from apex.provisioning import launching
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / defaults.BUILDER_KEY_NAME).write_bytes(b"key")
    for name in ("disk.qcow2", "code.fd", "vars.fd"):
        (base / name).write_bytes(b"")
    return safepaths.RuntimeRoot.adopt(base)


@pytest.fixture
def repository(tmp_path: Path) -> safepaths.SourceRoot:
    checkout = tmp_path / "checkout"
    (checkout / "config").mkdir(parents=True)
    shutil.copy(REPOSITORY / "config" / "sources.lock.json", checkout / "config")
    (checkout / "Containerfile").write_text("FROM scratch\n")
    return safepaths.SourceRoot.adopt(checkout)


def bundle(ports: portset.HostPorts, guest: fake_guestshell.ScriptedGuest) -> portset.HostPorts:
    return dataclasses.replace(
        ports,
        files=fake_files.MemoryFiles(),
        hypervisor=fake_hypervisor.FakeQemu(),
        monitor=fake_qmp.ScriptedQmp({"system_powerdown": {}}),
        clock=fake_clock.ManualClock(),
        downloads=fake_downloading.PinningFetcher(),
        guest=guest,
    )


def running(ports: portset.HostPorts, root: safepaths.RuntimeRoot, role: machines.VmRole) -> None:
    present = lambda name: safepaths.SafePath.regular_file(root.path / name, within=root)  # noqa: E731
    spec = machines.VmSpec.build(
        role=role,
        resources=machines.VmResources(memory=defaults.TEST_MACHINE.memory, processors=2),
        root_disk=present("disk.qcow2"),
        firmware=machines.Firmware(code=present("code.fd"), variables=present("vars.fd")),
        monitor=machines.MonitorSocket(root.child("qmp.sock")),
        serial=machines.SerialFile(root.child("serial.log")),
    )
    declared_real = type(
        "RealQemu", (fake_hypervisor.FakeQemu,), {"environment": claims.EnvironmentKind.BUILD}
    )
    launcher = dataclasses.replace(ports, hypervisor=declared_real())
    run = launcher.identities.run_id()
    launching.launch(
        launcher, root=root, spec=spec, run=run, run_directory=root.child(f"vm-runs/{run}")
    )
    hypervisor = ports.hypervisor
    assert isinstance(hypervisor, fake_hypervisor.FakeQemu)
    for spawned in launcher.hypervisor.spawned:  # type: ignore[attr-defined]
        hypervisor._alive[spawned.identity.process] = spawned.identity  # noqa: SLF001


def request(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot | None,
    repository: safepaths.SourceRoot,
    *arguments: str,
) -> commandspecs.Request:
    return commandspecs.Request(
        arguments=arguments,
        context=contexts.Context(
            settings=loader.load(host_file=None, environment={}),
            repository=repository,
            root=root,
            environment={},
            bundle=lambda _root: ports,
        ),
    )


def test_an_image_build_runs_in_the_leased_builder_and_replies_with_its_record(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    guest = AnsweringGuest({})
    held = bundle(ports, guest)
    running(held, root, machines.VmRole.BUILDER)

    reply = build_command.run(request(held, root, repository, "image"))

    assert reply.exit_code == 0
    assert isinstance(reply.document, dict)
    assert reply.document["succeeded"] is True
    record = reply.document["record"]
    assert isinstance(record, dict) and record["kind"] == "image" and record["status"] == "PASS"
    assert str(reply.document["exports"]).startswith(f"{root.path}/exports/")
    assert guest.targets[-1].user == "builder" and guest.targets[-1].port.value == 22244
    assert any("guest/build.sh fedora image" in run.script.rendered() for run in guest.runs)


def test_a_qcow2_with_test_access_is_derived_from_its_parent(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    repository: safepaths.SourceRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guest = AnsweringGuest({})
    held = bundle(ports, guest)
    running(held, root, machines.VmRole.BUILDER)
    documents(held.files, root)
    from apex.composition import accessgrant

    monkeypatch.setattr(
        accessgrant,
        "grant",
        lambda ports, *, root, run: accessgrant.Granted(
            directory=root.child(f"exports/{run}/test-access"),
            credentials=root.child(f"exports/{run}/test-access/credentials.json"),
            key=root.child(f"exports/{run}/test-access/id_ed25519"),
            blueprint=root.child(f"exports/{run}/test-access/blueprint.toml"),
        ),
    )

    reply = build_command.run(
        request(held, root, repository, "qcow2", "--parent", str(PARENT), "--test-access")
    )

    assert isinstance(reply.document, dict) and reply.document["succeeded"] is True
    record = reply.document["record"]
    assert isinstance(record, dict) and record["test_access"] is True
    access = reply.document["access"]
    assert isinstance(access, dict) and access["user"] == "apex-test"
    assert any(str(item.remote).endswith("test-blueprint.toml") for item in guest.sent)


def test_a_failed_guest_build_is_reported_with_its_log_and_the_refusal_exit(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    guest = AnsweringGuest({})
    held = bundle(ports, guest)
    running(held, root, machines.VmRole.BUILDER)
    failing = fake_guestshell.GuestReply(exit_code=1, stderr=b"build.sh: boom")

    original = guest.run

    def run(target: object, run: object) -> object:
        if "guest/build.sh" in run.script.rendered():  # type: ignore[attr-defined]
            guest.runs.append(run)  # type: ignore[arg-type]
            return dataclasses.replace(
                original(target, run),  # type: ignore[arg-type]
                exit_code=failing.exit_code,
                stderr=failing.stderr,
            )
        return original(target, run)  # type: ignore[arg-type]

    guest.run = run  # type: ignore[method-assign]

    reply = build_command.run(request(held, root, repository, "image"))

    assert reply.exit_code == errors.Refusal.exit_code
    assert isinstance(reply.document, dict) and reply.document["succeeded"] is False
    assert reply.document["refusal"] == str(refusals.RefusalReason.STAGE_FAILED)
    assert "retained log" in reply.narrative


@pytest.mark.parametrize(
    "arguments,reason",
    [
        (("qcow2",), refusals.RefusalReason.BUILD_PARENT_REQUIRED),
        (("image", "--parent", "d" * 32), refusals.RefusalReason.REQUEST_MALFORMED),
    ],
)
def test_a_request_that_contradicts_itself_is_refused_before_the_root_is_touched(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    repository: safepaths.SourceRoot,
    arguments: tuple[str, ...],
    reason: refusals.RefusalReason,
) -> None:
    with pytest.raises(errors.Refusal) as raised:
        build_command.run(request(bundle(ports, AnsweringGuest({})), root, repository, *arguments))

    assert raised.value.reason is reason


def test_test_access_on_an_installer_is_a_refused_outcome_with_exit_two(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    guest = AnsweringGuest({})
    held = bundle(ports, guest)
    running(held, root, machines.VmRole.BUILDER)
    documents(held.files, root)

    reply = build_command.run(
        request(held, root, repository, "installer", "--parent", str(PARENT), "--test-access")
    )

    assert reply.exit_code == errors.Refusal.exit_code
    assert isinstance(reply.document, dict)
    assert reply.document["refusal"] == "build.test-access-not-qcow2"
    assert guest.runs == []


def test_without_the_builder_a_build_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    held = bundle(ports, AnsweringGuest({}))

    with pytest.raises(errors.Refusal) as raised:
        build_command.run(request(held, root, repository, "image"))

    assert raised.value.reason is refusals.RefusalReason.MACHINE_NOT_RUNNING
    running(held, root, machines.VmRole.TEST)
    with pytest.raises(errors.Refusal) as mismatched:
        build_command.run(request(held, root, repository, "image"))
    assert mismatched.value.reason is refusals.RefusalReason.MACHINE_ROLE_MISMATCH


class DeliveringGuest(AnsweringGuest):
    """A guest whose received directory lands on the disk, as a real copy would."""

    outputs = {"other.qcow2": b"three foreign filesystems", "target.qcow2": b"an empty target"}

    def receive(
        self, target: Any, *, remote: Any, into: Any, recursive: bool, deadline: Any
    ) -> None:
        super().receive(target, remote=remote, into=into, recursive=recursive, deadline=deadline)
        home = into.path / posixpath.basename(str(remote))
        home.mkdir(parents=True, exist_ok=True)
        for name, data in self.outputs.items():
            (home / name).write_bytes(data)


def test_the_installer_fixture_disks_are_built_by_the_agent_in_the_leased_builder(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    (root.path / defaults.AGENT_WHEEL_NAME).write_bytes(b"wheel")
    guest = DeliveringGuest(
        {
            "fixture.installer-disks": {
                "sha256": {
                    name: hashlib.sha256(data).hexdigest()
                    for name, data in DeliveringGuest.outputs.items()
                }
            }
        }
    )
    held = bundle(ports, guest)
    running(held, root, machines.VmRole.BUILDER)

    reply = build_command.run(request(held, root, repository, "fixtures"))
    with pytest.raises(errors.Refusal) as derived:
        build_command.run(request(held, root, repository, "fixtures", "--parent", "b" * 32))

    assert reply.exit_code == 0
    assert isinstance(reply.document, dict) and reply.document["succeeded"] is True
    assert reply.document["record"] is None
    assert str(reply.document["fixtures"]).startswith(f"{root.path}/exports/")
    assert str(reply.document["fixtures"]).endswith("/output")
    assert guest.asked == ["fixture.installer-disks"]
    assert [str(item.remote) for item in guest.received][-1].endswith("/output")
    assert derived.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


class NvidiaGuest(AnsweringGuest):
    """A guest whose NVIDIA output lands on the disk and in the file port when retrieved."""

    def __init__(self, filesystem: Any) -> None:
        super().__init__({})
        self.filesystem = filesystem

    def receive(
        self, target: Any, *, remote: Any, into: Any, recursive: bool, deadline: Any
    ) -> None:
        super().receive(target, remote=remote, into=into, recursive=recursive, deadline=deadline)
        home = into.path / posixpath.basename(str(remote)) / defaults.NVIDIA_OUTPUT_DIRECTORY
        for name, data in nvidia.artifacts().items():
            (home / name).parent.mkdir(parents=True, exist_ok=True)
            (home / name).write_bytes(data)
        self.filesystem.write_atomic(
            safepaths.SafePath(home / defaults.NVIDIA_REPORT_NAME),
            json.dumps(nvidia.report(parentbuild_image_id())).encode(),
            mode=nvidia.PRIVATE,
        )


def parentbuild_image_id() -> str:
    from parentbuild import IMAGE_ID

    return IMAGE_ID


def test_the_nvidia_packages_are_built_for_a_frozen_parent_and_bound_to_it(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, repository: safepaths.SourceRoot
) -> None:
    filesystem = fake_files.MemoryFiles()
    guest = NvidiaGuest(filesystem)
    held = dataclasses.replace(bundle(ports, guest), files=filesystem)
    running(held, root, machines.VmRole.BUILDER)
    nvidia.write_lock(repository.path, filesystem)
    documents(filesystem, root, PARENT)
    filesystem.write_atomic(
        exports.inside(root, PARENT, f"output/{defaults.KERNEL_CONFIG_NAME}"),
        nvidia.kernel_config(),
        mode=nvidia.PRIVATE,
    )

    reply = build_command.run(request(held, root, repository, "nvidia", "--parent", str(PARENT)))
    with pytest.raises(errors.Refusal) as orphan:
        build_command.run(request(held, root, repository, "nvidia"))

    assert reply.exit_code == 0
    assert isinstance(reply.document, dict) and reply.document["succeeded"] is True
    record = reply.document["record"]
    assert isinstance(record, dict) and record["kind"] == "nvidia" and record["status"] == "PASS"
    verification = reply.document["nvidia"]
    assert isinstance(verification, dict) and verification["stage"] == "rpm-build"
    assert any("guest/nvidia-build.py" in run.script.rendered() for run in guest.runs)
    assert orphan.value.reason is refusals.RefusalReason.BUILD_PARENT_REQUIRED


@pytest.mark.parametrize(
    "arguments,reason",
    [
        (("fingerprint-rpms", "--parent", "d" * 32), refusals.RefusalReason.REQUEST_MALFORMED),
        (("fingerprint-image",), refusals.RefusalReason.BUILD_PARENT_REQUIRED),
        (
            ("fingerprint-image", "--parent", "d" * 32, "--rpm-build", "1" * 32),
            refusals.RefusalReason.REQUEST_MALFORMED,
        ),
        (("update-fixtures",), refusals.RefusalReason.BUILD_PARENT_REQUIRED),
        (
            ("update-fixtures", "--parent", "d" * 32, "--test-access"),
            refusals.RefusalReason.REQUEST_MALFORMED,
        ),
        (("recovery-disk",), refusals.RefusalReason.REQUEST_MALFORMED),
        (
            ("recovery-disk", "--fixture", "c" * 32, "--parent", "d" * 32),
            refusals.RefusalReason.REQUEST_MALFORMED,
        ),
    ],
)
def test_each_kind_takes_exactly_the_operands_its_recipe_seeds_from(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    repository: safepaths.SourceRoot,
    arguments: tuple[str, ...],
    reason: refusals.RefusalReason,
) -> None:
    with pytest.raises(errors.Refusal) as raised:
        build_command.run(request(bundle(ports, AnsweringGuest({})), root, repository, *arguments))

    assert raised.value.reason is reason


def test_the_fingerprint_packages_are_built_in_the_leased_builder_from_the_checkout(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    import fingerprintbuilds
    from mirroredfiles import MirroredFiles

    filesystem = MirroredFiles()
    scratch = MirroredFiles()
    fingerprintbuilds.rpm_build(scratch, root)
    home = root.path / "exports" / str(fingerprintbuilds.RPM_BUILD) / "output"
    outputs = {str(p.relative_to(home)): p.read_bytes() for p in home.rglob("*") if p.is_file()}
    shutil.rmtree(home.parent)

    class Guest(AnsweringGuest):
        def receive(
            self, target: Any, *, remote: Any, into: Any, recursive: bool, deadline: Any
        ) -> None:
            super().receive(
                target, remote=remote, into=into, recursive=recursive, deadline=deadline
            )
            base = into.path / posixpath.basename(str(remote))
            for name, data in outputs.items():
                filesystem.write_atomic(safepaths.SafePath(base / name), data, mode=nvidia.PRIVATE)

    guest = Guest({})
    held = dataclasses.replace(bundle(ports, guest), files=filesystem)
    running(held, root, machines.VmRole.BUILDER)

    reply = build_command.run(
        request(held, root, safepaths.SourceRoot.adopt(REPOSITORY), "fingerprint-rpms")
    )

    assert reply.exit_code == 0, reply.narrative
    assert isinstance(reply.document, dict) and reply.document["succeeded"] is True
    record = reply.document["record"]
    assert isinstance(record, dict) and record["kind"] == "fingerprint-rpms"
    verification = reply.document["fingerprint"]
    assert isinstance(verification, dict) and verification["status"] == "PASS"
    assert any("guest/fingerprint-rpms.py" in run.script.rendered() for run in guest.runs)

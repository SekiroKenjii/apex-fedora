"""The installer stages: the request before the fault, the kept report, the logs, the fixtures."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import posixpath
from pathlib import Path
from typing import Any

import installerruns
import pytest
from answeringguest import AnsweringGuest

from apex.adapters.fakes import fake_files
from apex.composition import agentrun
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import identifiers, refusals, safepaths
from apex.model import machines
from apex.pipeline import facts, stages
from apex.ports import guestshell, portset
from apex.verification import faults, installerfault, probes, verifykeys
from apex.verification.stages import (
    fault_stage,
    fixture_retrieve_stage,
    installer_keep_stage,
    installer_logs_stage,
    installer_request_stage,
    probe_stage,
    retain_report_stage,
)

SEED = identifiers.StageId("seed")
RUN = identifiers.RunId("f" * 32)
MACHINE_RUN = identifiers.RunId("e" * 32)
PAYLOAD = faults.lookup(identifiers.ProbeId("fault.installer-payload"))
DIAGNOSTICS = probes.lookup(identifiers.ProbeId("installer.diagnostics"))
DISKS = probes.lookup(identifiers.ProbeId("fixture.installer-disks"))


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "guest_ed25519").write_bytes(b"")
    return safepaths.RuntimeRoot.adopt(base)


def target(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user="root",
        port=defaults.GUEST_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "guest_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def context(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    guest: AnsweringGuest,
    **held: object,
) -> stages.RunContext[portset.HostPorts]:
    bundle = dataclasses.replace(ports, guest=guest, files=fake_files.MemoryFiles())
    given = facts.FactMap()
    seeded: dict[facts.FactKey[Any], object] = {
        verifykeys.GUEST: target(root),
        verifykeys.AGENT: agentrun.AgentInstall(
            directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
            digest=identifiers.Digest("a" * 64),
        ),
        verifykeys.MACHINE_RUN: root.child(f"vm-runs/{MACHINE_RUN}"),
        verifykeys.MACHINE_PROCESS: 4242,
        verifykeys.FAULT_CASE: installerruns.CASE,
        verifykeys.WRONG_KEY: "",
        composition_keys.RUNTIME_ROOT: root,
        composition_keys.RUN_ID: RUN,
    }
    for name, value in held.items():
        seeded[getattr(verifykeys, name.upper())] = value
    for key, value in seeded.items():
        given = given.with_fact(key, value, produced_by=SEED)
    return stages.RunContext(facts=given, ports=bundle)


def advanced(
    run: stages.RunContext[portset.HostPorts], stage: stages.SimpleStage[portset.HostPorts]
) -> stages.RunContext[portset.HostPorts]:
    result = stage.apply(run)
    assert isinstance(result, stages.Advance), result
    return run.with_facts(result.facts, by=stage.id)


def test_the_request_is_written_before_the_guest_is_touched_and_names_the_image(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    run = context(ports, root, AnsweringGuest({}))
    run_directory = run.facts[verifykeys.MACHINE_RUN]
    iso = installerruns.record(run.ports, root, run_directory)

    result = installer_request_stage.STAGE.apply(run)

    assert isinstance(result, stages.Advance)
    request = result.facts[verifykeys.INSTALLER_REQUEST]
    assert request.case == installerruns.CASE and request.process == 4242
    assert request.run == MACHINE_RUN
    image = run.ports.digests.file(safepaths.SafePath.regular_file(iso, within=root))
    assert request.image == image
    written = json.loads(run.ports.files.read_bytes(
        installerfault.request_path(run_directory), limit=1 << 20
    ))
    assert written["iso_sha256"] == request.image.hex and written["vm_pid"] == 4242
    again = installer_request_stage.STAGE.apply(run)
    assert isinstance(again, stages.Refuse)
    assert again.reason is refusals.RefusalReason.FAULT_ALREADY_ATTEMPTED


@pytest.mark.parametrize(
    "shape",
    [
        {"medium": machines.Medium.LIVE},
        {"serial_console": False},
        {"extras": 2},
        {"extras": 0},
    ],
)
def test_a_machine_that_is_not_the_installer_boot_the_fault_needs_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, shape: dict[str, Any]
) -> None:
    run = context(ports, root, AnsweringGuest({}))
    run_directory = run.facts[verifykeys.MACHINE_RUN]
    installerruns.record(run.ports, root, run_directory, **shape)

    result = installer_request_stage.STAGE.apply(run)

    assert isinstance(result, stages.Refuse)
    assert result.reason is refusals.RefusalReason.TOPOLOGY_INCONSISTENT
    assert not run.ports.files.exists(installerfault.request_path(run_directory))


def test_a_run_this_tree_did_not_start_has_no_record_and_is_refused(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    result = installer_request_stage.STAGE.apply(context(ports, root, AnsweringGuest({})))

    assert isinstance(result, stages.Refuse)
    assert result.reason is refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE


def test_the_fault_is_asked_with_the_case_and_its_report_is_kept_beside_the_machine_s_run(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"fault.installer-payload": installerruns.confirming()})
    run = context(ports, root, guest)
    run_directory = run.facts[verifykeys.MACHINE_RUN]
    installerruns.record(run.ports, root, run_directory)
    run = advanced(run, installer_request_stage.STAGE)
    arguments = lambda held: {  # noqa: E731
        "case": held.facts[verifykeys.FAULT_CASE],
        "wrong_public_key": held.facts[verifykeys.WRONG_KEY],
    }
    run = advanced(run, fault_stage.for_case(PAYLOAD, arguments=arguments))
    stage = installer_keep_stage.for_case(PAYLOAD)

    result = stage.apply(run)

    assert isinstance(result, stages.Advance)
    kept = result.facts[verifykeys.KEPT]
    assert kept.path == run_directory.path / defaults.FAULT_GUEST_NAME
    document = json.loads(run.ports.files.read_bytes(kept, limit=1 << 20))
    assert document["request"]["case"] == installerruns.CASE
    assert document["guest"]["verdict"] == "PASS" and document["guest"]["returncode"] == 1
    assert installerfault.confirmed(document["guest"], installerruns.CASE)
    assert guest.requests[0]["arguments"] == {"case": installerruns.CASE, "wrong_public_key": ""}
    assert str(stage.id) == "installer.keep"


def test_whole_logs_advance_and_the_first_incomplete_log_fails_the_run_by_name(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    stage = installer_logs_stage.for_case(DIAGNOSTICS)
    whole = context(
        ports, root, AnsweringGuest({"installer.diagnostics": installerruns.diagnostics()})
    )
    whole = advanced(whole, probe_stage.for_case(DIAGNOSTICS))
    whole = advanced(whole, retain_report_stage.for_probe(DIAGNOSTICS))
    truncated = installerruns.whole_log(b"partial")
    truncated["truncated"] = True
    broken = context(ports, root, AnsweringGuest({
        "installer.diagnostics": installerruns.diagnostics(**{"storage.log": truncated}),
    }))
    broken = advanced(broken, probe_stage.for_case(DIAGNOSTICS))
    broken = advanced(broken, retain_report_stage.for_probe(DIAGNOSTICS))
    missing = context(ports, root, AnsweringGuest({
        "installer.diagnostics": installerruns.diagnostics(**{
            "program.log": {"error": "not a regular file"}
        }),
    }))
    missing = advanced(missing, probe_stage.for_case(DIAGNOSTICS))
    missing = advanced(missing, retain_report_stage.for_probe(DIAGNOSTICS))

    passed = stage.apply(whole)
    failed = stage.apply(broken)
    absent = stage.apply(missing)

    assert isinstance(passed, stages.Advance) and passed.facts[verifykeys.LOGS_COMPLETE] is True
    assert isinstance(failed, stages.Fail) and failed.cause.startswith("storage.log truncated")
    assert isinstance(absent, stages.Fail) and "program.log not a regular file" in absent.cause
    assert verifykeys.retained_observation(DIAGNOSTICS) in stage.reads


class DeliveringGuest(AnsweringGuest):
    """A guest whose received directory lands on the disk, as a real copy would."""

    def __init__(self, answers: dict[str, Any], outputs: dict[str, bytes]) -> None:
        super().__init__(answers)
        self.outputs = outputs

    def receive(
        self,
        target: guestshell.GuestTarget,
        *,
        remote: safepaths.RemotePath,
        into: safepaths.SafePath,
        recursive: bool,
        deadline: Any,
    ) -> None:
        super().receive(target, remote=remote, into=into, recursive=recursive, deadline=deadline)
        home = into.path / posixpath.basename(str(remote))
        home.mkdir(parents=True, exist_ok=True)
        for name, data in self.outputs.items():
            (home / name).write_bytes(data)


def fixtures_report(outputs: dict[str, bytes]) -> dict[str, Any]:
    return {
        "purpose": "installer disk preservation tests",
        "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in outputs.items()},
    }


def test_the_fixture_disks_come_home_and_each_is_digested_against_the_builder_s_report(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    outputs = {"other.qcow2": b"three foreign filesystems", "target.qcow2": b"an empty target"}
    guest = DeliveringGuest({"fixture.installer-disks": fixtures_report(outputs)}, outputs)
    run = advanced(context(ports, root, guest), probe_stage.for_case(DISKS))
    stage = fixture_retrieve_stage.for_case(DISKS)

    result = stage.apply(run)

    assert isinstance(result, stages.Advance)
    home = result.facts[verifykeys.FIXTURES]
    assert home.path == root.path / "exports" / str(RUN) / "output"
    assert [str(item.remote) for item in guest.received] == [f"/var/tmp/apex-{RUN}/output"]
    assert guest.received[0].recursive and guest.received[0].into.path == home.path.parent
    assert "sudo chown -R builder:builder" in guest.runs[-1].script.rendered()


def test_a_fixture_that_differs_from_the_report_or_is_missing_fails_the_run(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    outputs = {"other.qcow2": b"three foreign filesystems", "target.qcow2": b"an empty target"}
    corrupted = DeliveringGuest(
        {"fixture.installer-disks": fixtures_report(outputs)},
        {**outputs, "target.qcow2": b"lost bytes"},
    )
    partial = DeliveringGuest(
        {"fixture.installer-disks": fixtures_report(outputs)},
        {"other.qcow2": outputs["other.qcow2"]},
    )
    unreported = DeliveringGuest(
        {"fixture.installer-disks": {"sha256": {"other.qcow2": "0" * 64}}}, outputs
    )
    stage = fixture_retrieve_stage.for_case(DISKS)

    results = [
        stage.apply(advanced(context(ports, root, guest), probe_stage.for_case(DISKS)))
        for guest in (corrupted, partial, unreported)
    ]

    assert all(isinstance(item, stages.Fail) for item in results)
    causes = [item.cause for item in results if isinstance(item, stages.Fail)]
    assert causes[0] == "target.qcow2: checksum mismatch after the transfer"
    assert causes[1].startswith("target.qcow2:")
    assert causes[2] == "the builder did not report both fixture disks"

"""The installer trust recipe, run end to end on fakes: no record minted, the report kept."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from answeringguest import AnsweringGuest

from apex.adapters.fakes import fake_files, fake_guestshell
from apex.composition import keys as composition_keys
from apex.composition.stages import check_builder_stage
from apex.config import defaults
from apex.kernel import refusals, safepaths, verdicts
from apex.ports import guestshell, portset
from apex.verification import verifykeys
from apex.verification.recipes import installer_trust_recipe


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "builder_ed25519").write_bytes(b"")
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def builder(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user=defaults.BUILDER_USER,
        port=defaults.BUILDER_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "builder_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def verify(ports: portset.HostPorts, root: safepaths.RuntimeRoot, guest: AnsweringGuest) -> object:
    assert isinstance(ports.files, fake_files.MemoryFiles)
    return installer_trust_recipe.verify(
        dataclasses.replace(ports, guest=guest),
        builder=builder(root),
        wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
        root=root,
    )


def test_the_plan_guards_delivers_makes_the_work_faults_and_keeps_the_report() -> None:
    assert [str(item) for item in installer_trust_recipe.PLAN.order] == [
        "builder.guard",
        "run.identify",
        "agent.deliver",
        "trust.work",
        "fault.installer-trust",
        "retain.fault.installer-trust",
    ]
    assert not any(stage.attests for stage in installer_trust_recipe.STAGES)


def test_the_fault_runs_over_its_work_and_the_report_is_kept_with_the_run(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({
        "fault.installer-trust": {"status": "PASS", "cases": {"unsigned": "PASS"}},
    })

    outcome = verify(ports, root, guest)

    assert outcome.succeeded is True  # type: ignore[attr-defined]
    assert outcome.attested == () and outcome.not_tested == ()  # type: ignore[attr-defined]
    assert guest.asked == ["fault.installer-trust"]
    facts = outcome.facts  # type: ignore[attr-defined]
    work = facts[verifykeys.WORK]
    run = facts[composition_keys.RUN_ID]
    assert str(work) == f"/var/tmp/apex-trust-{run}"
    assert guest.requests[0]["arguments"] == {"work": str(work)}
    assert "sudo" in guest.runs[-1].script.rendered()
    kept = facts[verifykeys.retained(installer_trust_recipe.CASE)]
    assert kept.path == root.path / "exports" / str(run) / "fault.installer-trust.json"
    assert json.loads(ports.files.read_bytes(kept, limit=1 << 20))["verdict"] == "PASS"
    report = facts[verifykeys.fault_report(installer_trust_recipe.CASE)]
    assert report.verdict is verdicts.PASSED


def test_a_guest_that_is_not_the_builder_stops_the_run(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"fault.installer-trust": {"status": "PASS"}})
    guest.expect(check_builder_stage.CHECK.rendered(), fake_guestshell.GuestReply(exit_code=1))

    outcome = verify(ports, root, guest)

    assert outcome.refusal is refusals.RefusalReason.BUILDER_NOT_ISOLATED  # type: ignore[attr-defined]
    assert guest.asked == [] and guest.sent == []

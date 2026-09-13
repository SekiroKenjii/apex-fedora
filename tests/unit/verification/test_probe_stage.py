"""A probe stage holds the guest's observation unjudged, and the retain stage keeps it as is."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
from answeringguest import AnsweringGuest

from apex.adapters.fakes import fake_guestshell
from apex.composition import agentrun
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import identifiers, refusals, safepaths
from apex.pipeline import effects, facts, stages
from apex.ports import guestshell, portset
from apex.verification import probes, verifykeys
from apex.verification.stages import probe_stage, retain_report_stage

SEED = identifiers.StageId("seed")
RUN = identifiers.RunId("d" * 32)
CASE = probes.lookup(identifiers.ProbeId("live.observe"))


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
    guest: fake_guestshell.ScriptedGuest,
    **held: object,
) -> stages.RunContext[portset.HostPorts]:
    given = facts.FactMap()
    seeded: dict[facts.FactKey[Any], object] = {
        verifykeys.GUEST: target(root),
        verifykeys.AGENT: agentrun.AgentInstall(
            directory=safepaths.RemotePath("/var/tmp/apex-run/agent"),
            digest=identifiers.Digest("a" * 64),
        ),
        composition_keys.RUNTIME_ROOT: root,
        composition_keys.RUN_ID: RUN,
    }
    for name, value in held.items():
        seeded[verifykeys.observed(CASE) if name == "observed" else name] = value  # type: ignore[index]
    for key, value in seeded.items():
        given = given.with_fact(key, value, produced_by=SEED)
    return stages.RunContext(facts=given, ports=dataclasses.replace(ports, guest=guest))


def test_the_stage_asks_the_unit_and_holds_the_whole_answer_without_a_verdict(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"live.observe": {"cmdline": "rd.live.image", "disks": ["vda"]}})
    stage = probe_stage.for_case(CASE)

    result = stage.apply(context(ports, root, guest))

    assert isinstance(result, stages.Advance)
    found = result.facts[verifykeys.observed(CASE)]
    assert found.case is CASE
    assert found.observations == {"cmdline": "rd.live.image", "disks": ["vda"]}
    assert b'"unit":"live.observe"' in found.proof.payload
    assert guest.asked == ["live.observe"]
    assert str(stage.id) == "live.observe"
    assert stage.effects == frozenset({effects.Effect.REMOTE_EXEC})
    assert not stage.attests


def test_a_unit_the_guest_does_not_know_is_the_stage_s_refusal(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    result = probe_stage.for_case(CASE).apply(context(ports, root, AnsweringGuest({})))

    assert isinstance(result, stages.Refuse)
    assert result.reason is refusals.RefusalReason.AGENT_REFUSED
    assert "agent.unit-unknown" in result.detail


def test_the_retained_observation_is_the_guest_s_document_with_no_verdict_added(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"live.observe": {"cmdline": "rd.live.image", "status": "PASS"}})
    run = context(ports, root, guest)
    observed = probe_stage.for_case(CASE).apply(run)
    assert isinstance(observed, stages.Advance)
    run = run.with_facts(observed.facts, by=identifiers.StageId("live.observe"))
    stage = retain_report_stage.for_probe(CASE)

    result = stage.apply(run)

    assert isinstance(result, stages.Advance)
    kept = result.facts[verifykeys.retained_observation(CASE)]
    assert kept.path == root.path / "exports" / str(RUN) / "live.observe.json"
    document = json.loads(run.ports.files.read_bytes(kept, limit=1 << 20))
    assert document == {"cmdline": "rd.live.image", "status": "PASS"}
    assert str(stage.id) == "retain.live.observe"
    assert set(stage.reads) == {
        verifykeys.observed(CASE), composition_keys.RUNTIME_ROOT, composition_keys.RUN_ID
    }

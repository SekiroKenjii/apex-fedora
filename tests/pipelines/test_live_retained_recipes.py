"""The three live recipes that keep what the guest said and mint nothing, run on fakes.

The older `test-live-check` cases reach the medium's rescue shell over serial and leave a
results file for the operator to cite when recording the check by hand. Each recipe here
is that: deliver the agent, ask one unit, keep its answer under the run's exports.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from answeringguest import AnsweringGuest

from apex.adapters.fakes import fake_files
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import refusals, safepaths, verdicts
from apex.ports import guestshell, portset
from apex.verification import verifykeys
from apex.verification.recipes import live_lock_recipe, live_observe_recipe, ventoy_observe_recipe


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def rescue(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user="root",
        port=defaults.GUEST_SSH_PORT,
        key=root.child(defaults.GUEST_KEY_NAME),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def run(
    recipe: object, ports: portset.HostPorts, root: safepaths.RuntimeRoot, guest: AnsweringGuest
) -> object:
    assert isinstance(ports.files, fake_files.MemoryFiles)
    return recipe.verify(  # type: ignore[attr-defined]
        dataclasses.replace(ports, guest=guest),
        guest=rescue(root),
        wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
        root=root,
    )


@pytest.mark.parametrize(
    ("recipe", "unit"),
    [
        (live_observe_recipe, "live.observe"),
        (ventoy_observe_recipe, "ventoy.observe"),
        (live_lock_recipe, "fault.live-lock"),
    ],
)
def test_each_plan_delivers_the_agent_asks_one_unit_and_keeps_its_answer(
    recipe: object, unit: str
) -> None:
    plan = recipe.PLAN  # type: ignore[attr-defined]

    assert [str(item) for item in plan.order] == [
        "run.identify",
        "agent.deliver",
        unit,
        f"retain.{unit}",
    ]
    assert not any(stage.attests for stage in plan.stages)
    assert plan.name == recipe.NAME  # type: ignore[attr-defined]


def test_a_probe_s_answer_is_kept_as_the_guest_gave_it(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"live.observe": {"cmdline": "rd.live.image", "mounts": ["/run/media"]}})

    outcome = run(live_observe_recipe, ports, root, guest)

    assert outcome.succeeded is True  # type: ignore[attr-defined]
    assert outcome.attested == () and outcome.not_tested == ()  # type: ignore[attr-defined]
    assert guest.asked == ["live.observe"]
    assert guest.targets[-1].user == "root"
    facts = outcome.facts  # type: ignore[attr-defined]
    run_id = facts[composition_keys.RUN_ID]
    kept = facts[verifykeys.retained_observation(live_observe_recipe.CASE)]
    assert kept.path == root.path / "exports" / str(run_id) / "live.observe.json"
    document = json.loads(ports.files.read_bytes(kept, limit=1 << 20))
    assert document == {"cmdline": "rd.live.image", "mounts": ["/run/media"]}


def test_the_ventoy_probe_is_the_same_shape_under_its_own_unit(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"ventoy.observe": {"ventoy": True, "device": "/dev/sdb"}})

    outcome = run(ventoy_observe_recipe, ports, root, guest)

    assert outcome.succeeded is True  # type: ignore[attr-defined]
    assert guest.asked == ["ventoy.observe"]
    kept = outcome.facts[verifykeys.retained_observation(ventoy_observe_recipe.CASE)]  # type: ignore[attr-defined]
    assert kept.path.name == "ventoy.observe.json"


def test_the_lock_fault_s_report_is_kept_with_the_verdict_the_host_drew(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"fault.live-lock": {"status": "PASS", "denied": True}})

    outcome = run(live_lock_recipe, ports, root, guest)

    assert outcome.succeeded is True  # type: ignore[attr-defined]
    facts = outcome.facts  # type: ignore[attr-defined]
    assert facts[verifykeys.fault_report(live_lock_recipe.CASE)].verdict is verdicts.PASSED
    kept = facts[verifykeys.retained(live_lock_recipe.CASE)]
    document = json.loads(ports.files.read_bytes(kept, limit=1 << 20))
    assert document == {"denied": True, "status": "PASS", "verdict": "PASS"}


def test_a_guest_that_does_not_know_the_unit_stops_the_run_before_anything_is_kept(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({})

    outcome = run(live_observe_recipe, ports, root, guest)

    assert outcome.succeeded is False  # type: ignore[attr-defined]
    assert outcome.refusal is refusals.RefusalReason.AGENT_REFUSED  # type: ignore[attr-defined]
    assert not (root.path / "exports").exists()

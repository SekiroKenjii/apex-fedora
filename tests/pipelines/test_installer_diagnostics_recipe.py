"""The installer diagnostics recipe on fakes: logs kept as given, the run failed if not whole."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import installerruns
import pytest
from answeringguest import AnsweringGuest

from apex.adapters.fakes import fake_files
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import refusals, safepaths
from apex.ports import guestshell, portset
from apex.verification import verifykeys
from apex.verification.recipes import installer_diagnostics_recipe


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def verify(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, guest: AnsweringGuest
) -> tuple[portset.HostPorts, object]:
    held = dataclasses.replace(ports, guest=guest, files=fake_files.MemoryFiles())
    return held, installer_diagnostics_recipe.verify(
        held,
        guest=guestshell.GuestTarget(
            user="root",
            port=defaults.GUEST_SSH_PORT,
            key=root.child(defaults.GUEST_KEY_NAME),
            known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
        ),
        wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
        root=root,
    )


def test_the_plan_asks_once_keeps_the_answer_and_then_judges_the_logs() -> None:
    assert [str(item) for item in installer_diagnostics_recipe.PLAN.order] == [
        "run.identify",
        "agent.deliver",
        "installer.diagnostics",
        "retain.installer.diagnostics",
        "installer.logs",
    ]
    assert not any(stage.attests for stage in installer_diagnostics_recipe.STAGES)


def test_whole_logs_are_kept_as_the_guest_gave_them_and_the_run_succeeds(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"installer.diagnostics": installerruns.diagnostics()})

    held, outcome = verify(ports, root, guest)

    assert outcome.succeeded is True  # type: ignore[attr-defined]
    facts = outcome.facts  # type: ignore[attr-defined]
    assert facts[verifykeys.LOGS_COMPLETE] is True
    kept = facts[verifykeys.retained_observation(installer_diagnostics_recipe.CASE)]
    run = facts[composition_keys.RUN_ID]
    assert kept.path == root.path / "exports" / str(run) / "installer.diagnostics.json"
    document = json.loads(held.files.read_bytes(kept, limit=1 << 20))
    assert document == installerruns.diagnostics()
    assert "verdict" not in document
    assert guest.asked == ["installer.diagnostics"]


def test_an_incomplete_log_fails_the_run_after_the_bundle_is_kept(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    truncated = installerruns.whole_log(b"partial")
    truncated["truncated"] = True
    guest = AnsweringGuest(
        {"installer.diagnostics": installerruns.diagnostics(**{"anaconda.log": truncated})}
    )

    _, outcome = verify(ports, root, guest)

    assert outcome.succeeded is False  # type: ignore[attr-defined]
    assert outcome.refusal is refusals.RefusalReason.STAGE_FAILED  # type: ignore[attr-defined]
    assert outcome.detail.startswith("installer.logs: anaconda.log truncated")  # type: ignore[attr-defined]
    assert verifykeys.retained_observation(installer_diagnostics_recipe.CASE) in outcome.facts  # type: ignore[attr-defined]

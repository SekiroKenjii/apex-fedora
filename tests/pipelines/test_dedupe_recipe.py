"""The blob sharing asked of the builder for one fixture, its report kept with the run."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from answeringguest import AnsweringGuest

from apex.adapters.fakes import fake_files
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import identifiers, safepaths
from apex.ports import guestshell, portset
from apex.verification import verifykeys
from apex.verification.recipes import dedupe_recipe

FIXTURE = identifiers.BuildId("c" * 32)


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "builder_ed25519").write_bytes(b"")
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def test_the_plan_guards_delivers_asks_for_the_fixture_and_keeps_the_report(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = AnsweringGuest({"fixture.dedupe": {"status": "PASS", "files_removed": 0}})
    files = fake_files.MemoryFiles()

    outcome = dedupe_recipe.verify(
        dataclasses.replace(ports, guest=guest, files=files),
        builder=guestshell.GuestTarget(
            user=defaults.BUILDER_USER,
            port=defaults.BUILDER_SSH_PORT,
            key=safepaths.SafePath.regular_file(root.path / "builder_ed25519", within=root),
            known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
        ),
        wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
        parent=FIXTURE,
        root=root,
    )

    assert outcome.succeeded, outcome.detail
    assert [str(item) for item in dedupe_recipe.PLAN.order] == [
        "builder.guard",
        "run.identify",
        "agent.deliver",
        "fixture.dedupe",
        "retain.fixture.dedupe",
    ]
    run = outcome.facts[composition_keys.RUN_ID]
    assert guest.requests[0]["arguments"] == {
        "work": f"/var/tmp/apex-dedupe-{run}",
        "fixture": str(FIXTURE),
    }
    kept = outcome.facts[verifykeys.retained_observation(dedupe_recipe.CASE)]
    assert kept.path.name == "fixture.dedupe.json"
    assert json.loads(files.read_bytes(kept, limit=4096))["files_removed"] == 0

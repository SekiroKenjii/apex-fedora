"""The installer fixture disks recipe on fakes: made in the builder, brought home, checked."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import posixpath
from pathlib import Path
from typing import Any

import pytest
from answeringguest import AnsweringGuest

from apex.adapters.fakes import fake_files
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import refusals, safepaths
from apex.ports import guestshell, portset
from apex.verification import verifykeys
from apex.verification.recipes import installer_fixtures_recipe

OUTPUTS = {"other.qcow2": b"three foreign filesystems", "target.qcow2": b"an empty target"}


class DeliveringGuest(AnsweringGuest):
    """A guest whose received directory lands on the disk, as a real copy would."""

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
        for name, data in OUTPUTS.items():
            (home / name).write_bytes(data)


def report() -> dict[str, Any]:
    return {
        "purpose": "installer disk preservation tests",
        "bootable_existing_systems": False,
        "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in OUTPUTS.items()},
    }


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "builder_ed25519").write_bytes(b"")
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def build(ports: portset.HostPorts, root: safepaths.RuntimeRoot, guest: AnsweringGuest) -> object:
    held = dataclasses.replace(ports, guest=guest, files=fake_files.MemoryFiles())
    return installer_fixtures_recipe.build(
        held,
        builder=guestshell.GuestTarget(
            user=defaults.BUILDER_USER,
            port=defaults.BUILDER_SSH_PORT,
            key=safepaths.SafePath.regular_file(root.path / "builder_ed25519", within=root),
            known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
        ),
        wheel=safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root),
        root=root,
    )


def test_the_plan_guards_delivers_makes_the_disks_brings_them_home_and_keeps_the_report() -> None:
    assert [str(item) for item in installer_fixtures_recipe.PLAN.order] == [
        "builder.guard",
        "run.identify",
        "agent.deliver",
        "fixture.installer-disks",
        "fixture.retrieve",
        "retain.fixture.installer-disks",
    ]
    assert not any(stage.attests for stage in installer_fixtures_recipe.STAGES)


def test_the_disks_are_made_under_the_run_s_directory_and_land_checked_under_its_exports(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    guest = DeliveringGuest({"fixture.installer-disks": report()})

    outcome = build(ports, root, guest)

    assert outcome.succeeded is True  # type: ignore[attr-defined]
    facts = outcome.facts  # type: ignore[attr-defined]
    run = facts[composition_keys.RUN_ID]
    assert guest.asked == ["fixture.installer-disks"]
    assert guest.requests[0]["arguments"] == {
        "work": f"/var/tmp/apex-{run}/work",
        "output": f"/var/tmp/apex-{run}/output",
        "token": str(run),
    }
    home = facts[verifykeys.FIXTURES]
    assert home.path == root.path / "exports" / str(run) / "output"
    assert (home.path / "other.qcow2").read_bytes() == OUTPUTS["other.qcow2"]
    kept = facts[verifykeys.retained_observation(installer_fixtures_recipe.CASE)]
    assert kept.path.name == "fixture.installer-disks.json"
    assert guest.targets[-1].user == "builder"


def test_a_disk_that_lost_bytes_on_the_way_fails_the_run_and_nothing_is_retained(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    damaged = report()
    damaged["sha256"]["target.qcow2"] = "0" * 64
    guest = DeliveringGuest({"fixture.installer-disks": damaged})

    outcome = build(ports, root, guest)

    assert outcome.succeeded is False  # type: ignore[attr-defined]
    assert outcome.refusal is refusals.RefusalReason.STAGE_FAILED  # type: ignore[attr-defined]
    assert "target.qcow2: checksum mismatch" in outcome.detail  # type: ignore[attr-defined]
    assert verifykeys.retained_observation(installer_fixtures_recipe.CASE) not in outcome.facts  # type: ignore[attr-defined]
    assert json.dumps(damaged["sha256"]) != json.dumps(report()["sha256"])

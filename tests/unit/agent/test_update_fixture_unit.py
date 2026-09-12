"""What the update fixture unit refuses before it builds anything."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_files,
    fake_ids,
    fake_process,
)
from apex.agent import agentports, builder
from apex.agent.units import update_fixture_unit
from apex.config import defaults
from apex.kernel import errors, hashing, quantities, refusals, safepaths
from apex.ports import containers

WORK = "/var/tmp/apex-update-" + "a" * 32
PRIVATE = quantities.FileMode(0o600)
RAW = b'{"config": {"digest": "sha256:' + b"c" * 64 + b'"}}'


def bundle(*, free: int = 100, raw: bytes = RAW) -> agentports.AgentPorts:
    process = fake_process.ScriptedProcess()
    process.expect(("systemd-detect-virt", "--vm"), fake_process.Reply(stdout=b"kvm\n"))
    process.expect(("sync", "-f", WORK), fake_process.Reply())
    files = fake_files.MemoryFiles()
    files.free = quantities.Gib(free).as_bytes()
    files.write_atomic(
        safepaths.SafePath(Path(defaults.BUILDER_MARKER)),
        f"{defaults.BUILDER_MARKER_TEXT}\n".encode(), mode=PRIVATE,
    )
    files.write_atomic(
        safepaths.SafePath(Path(WORK) / "target-image.json"),
        json.dumps({
            "profile": "fedora", "digest": str(hashing.digest_bytes(RAW)),
            "image_id": "sha256:" + "c" * 64,
        }).encode(),
        mode=PRIVATE,
    )
    registry = fake_containers.FakeRegistry()
    registry.manifest_of(
        containers.ImageReference.stored("localhost/apex-payload:" + hashing.digest_bytes(RAW).hex),
        raw,
    )
    return agentports.AgentPorts(
        processes=process,
        files=files,
        clock=fake_clock.ManualClock(),
        containers=registry,
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(),
    )


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)


def test_a_work_directory_not_named_for_a_run_is_refused() -> None:
    with pytest.raises(errors.Refusal) as raised:
        update_fixture_unit.run(bundle(), arguments={"work": "/var/tmp/somewhere"})

    assert raised.value.reason is refusals.RefusalReason.REQUEST_MALFORMED


def test_a_short_builder_stops_before_the_engine_is_asked() -> None:
    ports = bundle(free=1)

    with pytest.raises(errors.Refusal) as raised:
        update_fixture_unit.run(ports, arguments={"work": WORK})

    assert raised.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert isinstance(ports.containers, fake_containers.FakeRegistry)
    assert ports.containers.keys == []


def test_a_payload_whose_manifest_is_not_the_frozen_one_is_refused() -> None:
    ports = bundle(raw=b'{"config": {"digest": "sha256:' + b"e" * 64 + b'"}}')

    with pytest.raises(errors.Refusal) as raised:
        update_fixture_unit.run(ports, arguments={"work": WORK})

    assert raised.value.reason is refusals.RefusalReason.FROZEN_IMAGE_MISMATCH
    assert isinstance(ports.containers, fake_containers.FakeRegistry)
    assert ports.containers.keys == []

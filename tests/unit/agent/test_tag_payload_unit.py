"""The tag unit stands a stored fixture image in as the payload and writes its manifest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_blockdevices,
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_extents,
    fake_files,
    fake_ids,
    fake_process,
)
from apex.agent import agentports, builder
from apex.agent.units import tag_payload_unit
from apex.config import defaults
from apex.kernel import errors, hashing, identifiers, quantities, refusals, safepaths
from apex.ports import containers

WORK = "/var/tmp/apex-" + "a" * 32
SOURCE = "localhost/apex-recovery-" + "b" * 32 + ":a"
RAW = b'{"config": {"digest": "sha256:' + b"c" * 64 + b'"}}'
PRIVATE = quantities.FileMode(0o600)


def bundle(*, raw: bytes = RAW) -> agentports.AgentPorts:
    process = fake_process.ScriptedProcess()
    process.expect(("systemd-detect-virt", "--vm"), fake_process.Reply(stdout=b"kvm\n"))
    files = fake_files.MemoryFiles()
    files.write_atomic(
        safepaths.SafePath(Path(defaults.BUILDER_MARKER)),
        f"{defaults.BUILDER_MARKER_TEXT}\n".encode(), mode=PRIVATE,
    )
    registry = fake_containers.FakeRegistry()
    registry.manifest_of(containers.ImageReference.stored(SOURCE), raw)
    tag = f"{defaults.PAYLOAD_TAG_PREFIX}{hashing.digest_bytes(RAW).hex}"
    registry.hold(tag, identifiers.ImageId("c" * 64), b"{}")
    return agentports.AgentPorts(
        processes=process, files=files, clock=fake_clock.ManualClock(), containers=registry,
        digests=fake_digesting.CountingDigests(), archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(), extents=fake_extents.FakeExtents(),
        blocks=fake_blockdevices.FakeBlockDevices(),
    )


def arguments() -> dict[str, str]:
    return {"work": WORK, "source": SOURCE, "digest": str(hashing.digest_bytes(RAW))}


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)


def test_the_image_is_copied_under_the_payload_tag_and_its_manifest_written() -> None:
    ports = bundle()

    reply = tag_payload_unit.run(ports, arguments=arguments())

    tag = f"{defaults.PAYLOAD_TAG_PREFIX}{hashing.digest_bytes(RAW).hex}"
    assert reply["tag"] == tag and reply["image_id"] == "sha256:" + "c" * 64
    assert isinstance(ports.containers, fake_containers.FakeRegistry)
    copied = [str(item.source) for item in ports.containers.copies]
    assert copied == [f"containers-storage:{SOURCE}"]
    assert isinstance(ports.files, fake_files.MemoryFiles)
    written = ports.files.read_bytes(
        safepaths.SafePath(Path(WORK) / "output" / "payload-manifest.json"), limit=1 << 20
    )
    assert json.loads(written) == json.loads(RAW)


def test_a_source_whose_manifest_is_not_the_fixture_s_is_refused() -> None:
    ports = bundle(raw=b'{"config": {"digest": "sha256:' + b"e" * 64 + b'"}}')

    with pytest.raises(errors.Refusal) as raised:
        tag_payload_unit.run(ports, arguments=arguments())

    assert raised.value.reason is refusals.RefusalReason.IMAGE_METADATA_MISMATCH


@pytest.mark.parametrize(
    "change",
    [{"work": "/elsewhere"}, {"source": "docker.io/x:a"}, {"digest": "short"}],
)
def test_malformed_arguments_are_refused_before_the_engine_is_asked(change: dict[str, str]) -> None:
    ports = bundle()

    with pytest.raises(errors.Refusal) as raised:
        tag_payload_unit.run(ports, arguments={**arguments(), **change})

    assert raised.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert isinstance(ports.containers, fake_containers.FakeRegistry)
    assert ports.containers.copies == []

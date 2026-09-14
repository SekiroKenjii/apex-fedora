"""The payload import copies the parent's archive into the store and checks it twice over."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fingerprintfixtures import Builder, BuilderSpec

from apex.adapters.fakes import (
    fake_archives,
    fake_blockdevices,
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_extents,
    fake_files,
    fake_ids,
)
from apex.agent import agentports, builder
from apex.agent.units import import_payload_unit
from apex.config import defaults
from apex.kernel import errors, hashing, identifiers, quantities, refusals, safepaths
from apex.ports import containers

PARENT = "c" * 32
WORK = "/var/tmp/apex-fingerprint-" + "f" * 32
IMAGE_ID = "b" * 64
MANIFEST = json.dumps({"schemaVersion": 2, "config": {"digest": f"sha256:{IMAGE_ID}"}}).encode()
DIGEST = hashing.digest_bytes(MANIFEST)
ARCHIVE = f"/var/tmp/apex-{PARENT}/output/apex-fedora.oci.tar"
TAG = f"localhost/apex-payload:{DIGEST.hex}"
PUBLIC = quantities.FileMode(0o644)


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)


def guest(
    *, digest: str = str(DIGEST), stored: str = IMAGE_ID, archive: bool = True
) -> tuple[fake_containers.FakeRegistry, fake_files.MemoryFiles, agentports.AgentPorts]:
    files = fake_files.MemoryFiles()

    def write(path: Path, payload: bytes) -> None:
        files.write_atomic(safepaths.SafePath(path), payload, mode=PUBLIC)

    write(Path(defaults.BUILDER_MARKER), f"{defaults.BUILDER_MARKER_TEXT}\n".encode())
    target = {"profile": "fedora", "digest": digest, "image_id": f"sha256:{IMAGE_ID}"}
    write(Path(WORK) / "target-image.json", json.dumps(target).encode())
    if archive:
        write(Path(ARCHIVE), b"oci archive")
    registry = fake_containers.FakeRegistry()
    registry.manifest_of(
        containers.ImageReference(containers.Transport.OCI_ARCHIVE, ARCHIVE), MANIFEST
    )
    registry.hold(TAG, identifiers.ImageId(stored), b"[]")
    ports = agentports.AgentPorts(
        processes=Builder(BuilderSpec(), write),
        files=files,
        clock=fake_clock.ManualClock(),
        containers=registry,
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(),
        blocks=fake_blockdevices.FakeBlockDevices(),
    )
    return registry, files, ports


def test_the_archive_is_copied_into_the_store_and_the_manifest_filed() -> None:
    registry, files, ports = guest()

    report = import_payload_unit.run(ports, arguments={"work": WORK, "parent": PARENT})

    assert report == {
        "archive": ARCHIVE,
        "tag": TAG,
        "digest": str(DIGEST),
        "image_id": f"sha256:{IMAGE_ID}",
        "manifest": "output/payload-manifest.json",
    }
    assert [(str(item.source), str(item.destination), item.policy) for item in registry.copies] == [
        (f"oci-archive:{ARCHIVE}", f"containers-storage:{TAG}", None)
    ]
    filed = safepaths.SafePath(Path(WORK) / "output" / "payload-manifest.json")
    assert files.read_bytes(filed, limit=1 << 20) == MANIFEST


def test_a_manifest_that_hashes_to_another_digest_is_refused() -> None:
    registry, _, ports = guest(digest="sha256:" + "e" * 64)

    with pytest.raises(errors.Refusal) as caught:
        import_payload_unit.run(ports, arguments={"work": WORK, "parent": PARENT})

    assert caught.value.reason is refusals.RefusalReason.IMAGE_METADATA_MISMATCH
    assert len(registry.copies) == 1


def test_a_stored_image_other_than_the_targets_is_refused() -> None:
    _, _, ports = guest(stored="e" * 64)

    with pytest.raises(errors.Refusal) as caught:
        import_payload_unit.run(ports, arguments={"work": WORK, "parent": PARENT})

    assert caught.value.reason is refusals.RefusalReason.IMAGE_METADATA_MISMATCH


def test_an_archive_the_parent_did_not_leave_is_refused_before_any_copy() -> None:
    registry, _, ports = guest(archive=False)

    with pytest.raises(errors.Refusal) as caught:
        import_payload_unit.run(ports, arguments={"work": WORK, "parent": PARENT})

    assert caught.value.reason is refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE
    assert registry.copies == []


@pytest.mark.parametrize(
    "arguments", [{}, {"work": "/tmp/x", "parent": PARENT}, {"work": WORK, "parent": "not-a-build"}]
)
def test_a_request_outside_the_run_layout_is_refused(arguments: dict[str, str]) -> None:
    registry, _, ports = guest()

    with pytest.raises(errors.Refusal) as caught:
        import_payload_unit.run(ports, arguments=arguments)

    assert caught.value.reason is refusals.RefusalReason.REQUEST_MALFORMED
    assert registry.copies == []


def test_outside_the_isolated_builder_the_import_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builder.os, "geteuid", lambda: 1000)
    registry, _, ports = guest()

    with pytest.raises(errors.Refusal) as caught:
        import_payload_unit.run(ports, arguments={"work": WORK, "parent": PARENT})

    assert caught.value.reason is refusals.RefusalReason.BUILDER_NOT_ISOLATED
    assert registry.copies == []

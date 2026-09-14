"""The dedupe unit proves what the older script proved, and refuses the same builders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_blockdevices,
    fake_clock,
    fake_containers,
    fake_extents,
    fake_ids,
    fake_process,
)
from apex.adapters.real import real_digesting, real_files
from apex.agent import agentports, builder
from apex.agent.units import dedupe_unit
from apex.config import defaults
from apex.kernel import errors, hashing, refusals
from apex.provisioning.fixtures import dedupe_fixture

BLOB = b"layer bytes" * 1000


def bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    filesystem: str = "btrfs",
    containers_running: bytes = b"[]",
) -> tuple[agentports.AgentPorts, fake_extents.FakeExtents]:
    marker = tmp_path / "apex-builder"
    marker.write_text(f"{defaults.BUILDER_MARKER_TEXT}\n")
    monkeypatch.setattr(defaults, "BUILDER_MARKER", str(marker))
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    monkeypatch.setattr(dedupe_unit.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(dedupe_unit.os, "sync", lambda: None)
    monkeypatch.setattr(dedupe_unit, "WORK_PREFIX", str(tmp_path / "apex-dedupe-"))
    monkeypatch.setattr(dedupe_unit, "UPDATE_PREFIX", str(tmp_path / "apex-update-"))
    process = fake_process.ScriptedProcess()
    process.expect(("systemd-detect-virt", "--vm"), fake_process.Reply(stdout=b"kvm\n"))
    process.expect(
        ("findmnt", "-n", "-o", "FSTYPE", "-T", "/var/tmp"),
        fake_process.Reply(stdout=f"{filesystem}\n".encode()),
    )
    registry = fake_containers.FakeRegistry()
    registry.containers_listing = containers_running
    shares = fake_extents.FakeExtents()
    ports = agentports.AgentPorts(
        processes=process,
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        containers=registry,
        digests=real_digesting.CachedDigests(),
        archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(),
        extents=shares,
        blocks=fake_blockdevices.FakeBlockDevices(),
    )
    return ports, shares


def test_the_self_test_shares_refuses_and_isolates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ports, shares = bundle(tmp_path, monkeypatch)
    work = tmp_path / ("apex-dedupe-" + "a" * 32)

    report = dedupe_unit.run(ports, arguments={"work": str(work)})

    assert report["status"] == "PASS"
    self_test = report["self_test"]
    assert isinstance(self_test, dict)
    assert self_test["kernel_rejected_difference"] is True
    assert self_test["cow_write_isolation"] is True
    identical = self_test["identical"]
    assert isinstance(identical, dict)
    assert identical["bytes_submitted"] == dedupe_fixture.SELF_TEST_SIZE.bytes
    assert [str(item.target.path.name) for item in shares.requests] == ["target", "different"]
    assert json.loads((work / "result.json").read_text())["status"] == "PASS"


def test_a_completed_fixture_has_its_blobs_shared_and_its_manifests_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ports, shares = bundle(tmp_path, monkeypatch)
    fixture = "b" * 32
    root = tmp_path / f"apex-update-{fixture}"
    manifest = b'{"config": {"digest": "sha256:' + b"c" * 64 + b'"}}'
    blob_name = hashing.digest_bytes(BLOB).hex
    for directory in ("bundle/b", "wrong-signed"):
        (root / directory).mkdir(parents=True)
        (root / directory / "manifest.json").write_bytes(manifest)
        (root / directory / blob_name).write_bytes(BLOB)
        (root / directory / "signature-1").write_bytes(directory.encode())
    (root / "output").mkdir()
    (root / "output" / "results.json").write_text(
        json.dumps(
            {
                "status": "PASS",
                "id": fixture,
                "images": {
                    "a": {
                        "digest": "sha256:" + "a" * 64,
                        "config": "sha256:" + "c" * 64,
                        "identity": "x",
                    },
                    "b": {
                        "digest": str(hashing.digest_bytes(manifest)),
                        "config": "sha256:" + "c" * 64,
                        "identity": "y",
                    },
                },
                "files": {},
                "public_key_sha256": "d" * 64,
                "archive_sha256": "e" * 64,
            }
        )
    )
    work = tmp_path / ("apex-dedupe-" + "a" * 32)

    report = dedupe_unit.run(ports, arguments={"work": str(work), "fixture": fixture})

    assert report["status"] == "PASS"
    files = report["files"]
    assert isinstance(files, dict)
    assert set(files) == {blob_name}
    preserved = report["preserved_sha256"]
    assert isinstance(preserved, dict)
    assert len(preserved) == 4
    assert (root / "bundle/b" / "signature-1").read_bytes() == b"bundle/b"
    assert any(item.target.path.name == blob_name for item in shares.requests)


def test_a_scratch_that_is_not_btrfs_is_refused_before_anything_is_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ports, shares = bundle(tmp_path, monkeypatch, filesystem="ext4")

    with pytest.raises(errors.Refusal) as raised:
        dedupe_unit.run(ports, arguments={"work": str(tmp_path / ("apex-dedupe-" + "a" * 32))})

    assert raised.value.reason is refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED
    assert shares.requests == []


def test_running_containers_stop_the_unit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ports, shares = bundle(tmp_path, monkeypatch, containers_running=b'[{"Id": "x"}]')

    with pytest.raises(errors.Refusal):
        dedupe_unit.run(ports, arguments={"work": str(tmp_path / ("apex-dedupe-" + "a" * 32))})

    assert shares.requests == []

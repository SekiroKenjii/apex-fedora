"""Acquiring the locked sources: every pin checked, nothing fetched twice, nothing unpinned."""

from __future__ import annotations

import json

import pytest

from apex.adapters.fakes import (
    fake_clock,
    fake_downloading,
    fake_guestshell,
    fake_hypervisor,
    fake_ids,
    fake_locking,
    fake_process,
    fake_qmp,
    fake_signing,
)
from apex.adapters.real import real_archives, real_digesting, real_files
from apex.config import defaults
from apex.kernel import errors, hashing, refusals, safepaths
from apex.model import sourcelock
from apex.ports import downloading, portset
from apex.trust import acquiring

BODIES = {"alpha": b"alpha archive", "beta": b"beta archive"}
IMAGE_DIGEST = "sha256:" + "1" * 64


def lock_document() -> bytes:
    document = {
        "schema": 1,
        "base": {"reference": f"quay.io/x/base@{IMAGE_DIGEST}", "digest": IMAGE_DIGEST},
        "image_builder": {"reference": f"ghcr.io/x/ib@{IMAGE_DIGEST}", "digest": IMAGE_DIGEST},
        "sources": {
            name: {
                "url": f"https://example.invalid/{name}.tar.gz",
                "sha256": hashing.digest_bytes(body).hex,
            }
            for name, body in BODIES.items()
        },
    }
    return json.dumps(document).encode()


def served() -> dict[str, bytes]:
    return {f"https://example.invalid/{name}.tar.gz": body for name, body in BODIES.items()}


def bundle(fetcher: downloading.DownloadPort) -> portset.HostPorts:
    return portset.HostPorts(
        processes=fake_process.ScriptedProcess(),
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        identities=fake_ids.SequenceIdentities(),
        locks=fake_locking.MemoryLocks(),
        digests=real_digesting.CachedDigests(),
        archives=real_archives.TarArchives(),
        signing=fake_signing.FakeSigner(),
        downloads=fetcher,
        hypervisor=fake_hypervisor.FakeQemu(),
        monitor=fake_qmp.ScriptedQmp(),
        guest=fake_guestshell.ScriptedGuest(),
    )


def reviewed() -> acquiring.ReviewedLock:
    document = lock_document()
    return acquiring.ReviewedLock(lock=sourcelock.parse(json.loads(document)), document=document)


def test_every_locked_source_is_fetched_and_the_lock_is_recorded(
    root: safepaths.RuntimeRoot,
) -> None:
    fetcher = fake_downloading.OfflineFetcher(served())

    result = acquiring.acquire(bundle(fetcher), reviewed=reviewed(), root=root)

    assert sorted(fetcher.fetched) == sorted(served())
    assert {item.name: item.fetched for item in result.sources} == {"alpha": True, "beta": True}
    for name, body in BODIES.items():
        stored = root.path / defaults.SOURCES_DIRECTORY / f"{name}.tar.gz"
        assert stored.read_bytes() == body
        assert stored.stat().st_mode & 0o077 == 0
    recorded = root.path / defaults.LOCK_COPY_NAME
    assert json.loads(recorded.read_bytes()) == json.loads(lock_document())
    assert recorded.stat().st_mode & 0o077 == 0


def test_a_source_already_present_with_its_digest_is_not_fetched_again(
    root: safepaths.RuntimeRoot,
) -> None:
    first = fake_downloading.OfflineFetcher(served())
    acquiring.acquire(bundle(first), reviewed=reviewed(), root=root)
    second = fake_downloading.OfflineFetcher(served())

    result = acquiring.acquire(bundle(second), reviewed=reviewed(), root=root)

    assert second.fetched == []
    assert all(not item.fetched for item in result.sources)


def test_a_cached_source_whose_bytes_changed_is_fetched_again(root: safepaths.RuntimeRoot) -> None:
    first = fake_downloading.OfflineFetcher(served())
    acquiring.acquire(bundle(first), reviewed=reviewed(), root=root)
    (root.path / defaults.SOURCES_DIRECTORY / "alpha.tar.gz").write_bytes(b"corrupted")
    again = fake_downloading.OfflineFetcher(served())

    acquiring.acquire(bundle(again), reviewed=reviewed(), root=root)

    assert again.fetched == ["https://example.invalid/alpha.tar.gz"]
    assert (root.path / defaults.SOURCES_DIRECTORY / "alpha.tar.gz").read_bytes() == BODIES["alpha"]


def test_a_body_that_does_not_match_its_pin_is_refused_and_kept_for_inspection(
    root: safepaths.RuntimeRoot,
) -> None:
    tampered = {**served(), "https://example.invalid/beta.tar.gz": b"not beta"}

    with pytest.raises(errors.Refusal) as raised:
        acquiring.acquire(
            bundle(fake_downloading.OfflineFetcher(tampered)), reviewed=reviewed(), root=root
        )

    assert raised.value.reason is refusals.RefusalReason.DOWNLOAD_CHECKSUM_MISMATCH
    assert not (root.path / defaults.SOURCES_DIRECTORY / "beta.tar.gz").exists()
    assert (root.path / defaults.SOURCES_DIRECTORY / "beta.tar.gz.part").exists()
    assert not (root.path / defaults.LOCK_COPY_NAME).exists()


def test_a_run_without_a_network_refuses_before_anything_is_written(
    root: safepaths.RuntimeRoot,
) -> None:
    with pytest.raises(errors.Refusal) as raised:
        acquiring.acquire(
            bundle(fake_downloading.RefusingNetwork()), reviewed=reviewed(), root=root
        )

    assert raised.value.reason is refusals.RefusalReason.NETWORK_NOT_PERMITTED
    assert not (root.path / defaults.LOCK_COPY_NAME).exists()

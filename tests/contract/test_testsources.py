"""Acquiring the pinned test files: each pin checked, none fetched twice, laid out for the guest."""

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
from apex.config import defaults, fingerprintpins
from apex.kernel import errors, hashing, refusals, safepaths
from apex.model import pinnedfiles
from apex.ports import downloading, portset
from apex.trust import testsources

BASE = "https://example.invalid/tests/"
BODIES = {
    "fprintd.py": b"# upstream cases\n",
    "output_checker.py": b"# output checker\n",
    "dbusmock/polkitd.py": b"# polkit mock\n",
}


def lock_document() -> bytes:
    document = {
        "version": "1.94.5",
        "base_url": BASE,
        "files": {name: hashing.digest_bytes(body).hex for name, body in BODIES.items()},
    }
    return json.dumps(document).encode()


def served() -> dict[str, bytes]:
    return {f"{BASE}{name}": body for name, body in BODIES.items()}


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


def reviewed() -> fingerprintpins.ReviewedFiles:
    document = lock_document()
    return fingerprintpins.ReviewedFiles(
        files=pinnedfiles.parse(json.loads(document)), document=document
    )


def test_every_pinned_file_is_fetched_beside_the_lock_as_the_harness_expects_them(
    root: safepaths.RuntimeRoot,
) -> None:
    fetcher = fake_downloading.OfflineFetcher(served())

    result = testsources.acquire(bundle(fetcher), reviewed=reviewed(), root=root)

    assert sorted(fetcher.fetched) == sorted(served())
    assert {item.name: item.fetched for item in result.files} == dict.fromkeys(BODIES, True)
    assert result.directory.path == root.path / defaults.FINGERPRINT_TESTS_DIRECTORY
    sources = testsources.sources_directory(root).path
    for name, body in BODIES.items():
        assert (sources / name).read_bytes() == body
        assert (sources / name).stat().st_mode & 0o077 == 0
    recorded = testsources.lock_copy(root).path
    assert recorded == result.directory.path / "config" / "fingerprint-tests.lock.json"
    assert json.loads(recorded.read_bytes()) == json.loads(lock_document())
    assert result.lock_record == hashing.digest_bytes(lock_document())


def test_a_file_already_present_with_its_digest_is_not_fetched_again(
    root: safepaths.RuntimeRoot,
) -> None:
    testsources.acquire(
        bundle(fake_downloading.OfflineFetcher(served())), reviewed=reviewed(), root=root
    )
    again = fake_downloading.OfflineFetcher(served())

    result = testsources.acquire(bundle(again), reviewed=reviewed(), root=root)

    assert again.fetched == []
    assert all(not item.fetched for item in result.files)


def test_a_held_file_whose_bytes_changed_is_fetched_again(root: safepaths.RuntimeRoot) -> None:
    testsources.acquire(
        bundle(fake_downloading.OfflineFetcher(served())), reviewed=reviewed(), root=root
    )
    changed = testsources.sources_directory(root).path / "dbusmock" / "polkitd.py"
    changed.write_bytes(b"edited")
    again = fake_downloading.OfflineFetcher(served())

    testsources.acquire(bundle(again), reviewed=reviewed(), root=root)

    assert again.fetched == [f"{BASE}dbusmock/polkitd.py"]
    assert changed.read_bytes() == BODIES["dbusmock/polkitd.py"]


def test_a_body_that_does_not_match_its_pin_is_refused_and_the_lock_is_not_recorded(
    root: safepaths.RuntimeRoot,
) -> None:
    tampered = {**served(), f"{BASE}output_checker.py": b"not the checker"}

    with pytest.raises(errors.Refusal) as raised:
        testsources.acquire(
            bundle(fake_downloading.OfflineFetcher(tampered)), reviewed=reviewed(), root=root
        )

    assert raised.value.reason is refusals.RefusalReason.DOWNLOAD_CHECKSUM_MISMATCH
    sources = testsources.sources_directory(root).path
    assert not (sources / "output_checker.py").exists()
    assert (sources / "output_checker.py.part").exists()
    assert not testsources.lock_copy(root).path.exists()


def test_a_run_without_a_network_refuses_before_anything_is_written(
    root: safepaths.RuntimeRoot,
) -> None:
    with pytest.raises(errors.Refusal) as raised:
        testsources.acquire(
            bundle(fake_downloading.RefusingNetwork()), reviewed=reviewed(), root=root
        )

    assert raised.value.reason is refusals.RefusalReason.NETWORK_NOT_PERMITTED
    assert not (root.path / defaults.FINGERPRINT_TESTS_DIRECTORY).exists()

"""Fetching a pinned archive. The address is https by type and the checksum is required.

The real adapter's happy path needs a network, so it is exercised by `just sources` on a
connected machine and not here. What both adapters share is the shape of a failure: an
unreachable address is a port failure, and a checksum mismatch keeps the partial download for
inspection and never replaces the destination.
"""

from __future__ import annotations

import pytest

from apex.adapters.fakes import fake_downloading
from apex.kernel import errors, hashing, locators, refusals, safepaths, timing
from apex.ports import downloading as download_port

UNREACHABLE = locators.HttpsUrl("https://127.0.0.1:9/nothing.tar.gz")
DEADLINE = timing.Deadline(timing.Elapsed(5))
BODY = b"archive bytes"


def test_an_unreachable_address_is_a_port_failure(
    downloads: download_port.DownloadPort, root: safepaths.RuntimeRoot
) -> None:
    with pytest.raises(errors.PortFailure):
        downloads.fetch(
            UNREACHABLE,
            into=root.child("sources/nothing.tar.gz"),
            expected=hashing.digest_bytes(BODY),
            deadline=DEADLINE,
        )
    assert not (root.path / "sources" / "nothing.tar.gz").exists()


def test_a_served_archive_lands_at_its_destination_with_its_digest(
    root: safepaths.RuntimeRoot,
) -> None:
    url = locators.HttpsUrl("https://example.invalid/a.tar.gz")
    fetcher = fake_downloading.OfflineFetcher({str(url): BODY})
    target = root.child("sources/a.tar.gz")

    digest = fetcher.fetch(url, into=target, expected=hashing.digest_bytes(BODY), deadline=DEADLINE)

    assert digest == hashing.digest_bytes(BODY)
    assert target.path.read_bytes() == BODY
    assert target.path.stat().st_mode & 0o077 == 0


def test_a_checksum_mismatch_keeps_the_partial_download_and_refuses(
    root: safepaths.RuntimeRoot,
) -> None:
    url = locators.HttpsUrl("https://example.invalid/a.tar.gz")
    fetcher = fake_downloading.OfflineFetcher({str(url): BODY})
    target = root.child("sources/a.tar.gz")

    with pytest.raises(errors.Refusal) as raised:
        fetcher.fetch(url, into=target, expected=hashing.digest_bytes(b"other"), deadline=DEADLINE)

    assert raised.value.reason is refusals.RefusalReason.DOWNLOAD_CHECKSUM_MISMATCH
    assert not target.path.exists()
    assert (root.path / "sources" / "a.tar.gz.part").read_bytes() == BODY


def test_the_refusing_network_never_fetches(root: safepaths.RuntimeRoot) -> None:
    with pytest.raises(errors.Refusal) as raised:
        fake_downloading.RefusingNetwork().fetch(
            UNREACHABLE,
            into=root.child("sources/x"),
            expected=hashing.digest_bytes(BODY),
            deadline=DEADLINE,
        )

    assert raised.value.reason is refusals.RefusalReason.NETWORK_NOT_PERMITTED

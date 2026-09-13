"""Hashing files. A cache is an optimisation and never an integrity decision."""

from __future__ import annotations

from typing import Protocol

from apex.kernel import hashing, safepaths
from apex.ports import digesting as digest_port


class CountsReads(digest_port.DigestPort, Protocol):
    """Both adapters count reads for this suite; the port itself does not promise to."""

    reads: int


def written(root: safepaths.RuntimeRoot, name: str, payload: bytes) -> safepaths.SafePath:
    target = root.path / name
    target.write_bytes(payload)
    return safepaths.SafePath.regular_file(target, within=root)


def test_a_file_digest_matches_the_bytes(
    digests: digest_port.DigestPort, root: safepaths.RuntimeRoot
) -> None:
    path = written(root, "a.bin", b"payload")

    assert digests.file(path) == hashing.digest_bytes(b"payload")


def test_hashing_twice_gives_the_same_answer(
    digests: digest_port.DigestPort, root: safepaths.RuntimeRoot
) -> None:
    path = written(root, "a.bin", b"payload")

    assert digests.file(path) == digests.file(path)


def test_a_changed_file_gives_a_different_digest(
    digests: digest_port.DigestPort, root: safepaths.RuntimeRoot
) -> None:
    path = written(root, "a.bin", b"before")
    first = digests.file(path)

    path.path.write_bytes(b"after")

    assert digests.file(path) != first


def test_the_second_hash_of_an_unchanged_file_is_served_from_the_cache(
    digests: CountsReads, root: safepaths.RuntimeRoot
) -> None:
    path = written(root, "a.bin", b"payload")

    digests.file(path)
    before = digests.reads
    digests.file(path)

    assert digests.reads == before


def test_a_changed_file_is_read_again(digests: CountsReads, root: safepaths.RuntimeRoot) -> None:
    path = written(root, "a.bin", b"before")
    digests.file(path)
    before = digests.reads

    path.path.write_bytes(b"different length")
    digests.file(path)

    assert digests.reads > before


def test_a_cold_cache_produces_the_same_answer(
    digests: digest_port.DigestPort, root: safepaths.RuntimeRoot
) -> None:
    path = written(root, "a.bin", b"payload")
    warm = digests.file(path)

    digests.forget()

    assert digests.file(path) == warm


def test_an_empty_file_hashes_to_the_empty_digest(
    digests: digest_port.DigestPort, root: safepaths.RuntimeRoot
) -> None:
    path = written(root, "empty.bin", b"")

    assert digests.file(path) == hashing.digest_bytes(b"")

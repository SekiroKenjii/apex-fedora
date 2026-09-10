"""Hashing is streamed, and a cache key describes the file rather than its name."""

from __future__ import annotations

import hashlib
from pathlib import Path

from apex.kernel import hashing, identifiers


def test_a_stream_digest_matches_the_standard_library() -> None:
    payload = b"apex" * 1000

    assert hashing.digest_bytes(payload).hex == hashlib.sha256(payload).hexdigest()


def test_a_stream_digest_is_computed_in_chunks() -> None:
    payload = b"x" * (hashing.READ_CHUNK * 3 + 7)

    def chunks():
        for start in range(0, len(payload), 1024):
            yield payload[start : start + 1024]

    assert hashing.digest_stream(chunks()) == hashing.digest_bytes(payload)


def test_a_digest_of_no_bytes_is_the_empty_digest() -> None:
    assert hashing.digest_bytes(b"").hex == hashlib.sha256(b"").hexdigest()


def test_a_stat_key_describes_the_file_not_its_path(tmp_path: Path) -> None:
    target = tmp_path / "a.json"
    target.write_text("{}")
    moved = tmp_path / "b.json"

    before = hashing.StatKey.of(target)
    target.rename(moved)
    after = hashing.StatKey.of(moved)

    assert before == after


def test_a_stat_key_changes_when_the_content_changes(tmp_path: Path) -> None:
    target = tmp_path / "a.json"
    target.write_text("{}")
    before = hashing.StatKey.of(target)

    target.write_text('{"changed": true}')

    assert hashing.StatKey.of(target) != before


def test_a_merkle_root_is_stable_for_the_same_ordered_leaves() -> None:
    leaves = [hashing.digest_bytes(b"a"), hashing.digest_bytes(b"b")]

    assert hashing.merkle_root(leaves) == hashing.merkle_root(list(leaves))


def test_a_merkle_root_changes_when_a_leaf_changes() -> None:
    first = hashing.merkle_root([hashing.digest_bytes(b"a"), hashing.digest_bytes(b"b")])
    second = hashing.merkle_root([hashing.digest_bytes(b"a"), hashing.digest_bytes(b"c")])

    assert first != second


def test_a_merkle_root_depends_on_order() -> None:
    first = hashing.merkle_root([hashing.digest_bytes(b"a"), hashing.digest_bytes(b"b")])
    second = hashing.merkle_root([hashing.digest_bytes(b"b"), hashing.digest_bytes(b"a")])

    assert first != second


def test_a_merkle_root_is_a_digest() -> None:
    root = hashing.merkle_root([hashing.digest_bytes(b"a")])

    assert isinstance(root, identifiers.MerkleRoot)

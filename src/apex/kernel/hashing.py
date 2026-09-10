"""Streaming digests and a cache key that survives a rename."""

from __future__ import annotations

import dataclasses
import hashlib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Self

from apex.kernel import identifiers

READ_CHUNK = 1024 * 1024
_LEAF_PREFIX = b"\x00"
_NODE_PREFIX = b"\x01"


def digest_bytes(payload: bytes) -> identifiers.Digest:
    return identifiers.Digest(hashlib.sha256(payload).hexdigest())


def digest_stream(chunks: Iterable[bytes]) -> identifiers.Digest:
    hasher = hashlib.sha256()
    for chunk in chunks:
        hasher.update(chunk)
    return identifiers.Digest(hasher.hexdigest())


def merkle_root(leaves: Sequence[identifiers.Digest]) -> identifiers.MerkleRoot:
    hasher = hashlib.sha256()
    hasher.update(_LEAF_PREFIX if len(leaves) == 1 else _NODE_PREFIX)
    for leaf in leaves:
        hasher.update(leaf.hex.encode())
    return identifiers.MerkleRoot(hasher.hexdigest())


@dataclasses.dataclass(frozen=True, slots=True)
class StatKey:
    device: int
    inode: int
    size: int
    modified_nanoseconds: int

    @classmethod
    def of(cls, path: Path) -> Self:
        info = path.stat()
        return cls(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

"""Deterministic source bundles.

The archive is the input a build is reproduced from, so its digest must depend on the files
and on nothing else: not on the order the filesystem returned them, not on when they were
last written.
"""

from __future__ import annotations

import dataclasses
from typing import Protocol

from apex.kernel import claims, identifiers, quantities, safepaths


@dataclasses.dataclass(frozen=True, slots=True)
class SourceSet:
    root: safepaths.RuntimeRoot
    relative_paths: tuple[str, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class BundledFile:
    path: str
    mode: quantities.FileMode
    digest: identifiers.Digest


@dataclasses.dataclass(frozen=True, slots=True)
class SourceBundle:
    archive: safepaths.SafePath
    files: tuple[BundledFile, ...]
    merkle_root: identifiers.MerkleRoot
    reads: int


class ArchivePort(Protocol):
    environment: claims.EnvironmentKind

    def bundle(self, sources: SourceSet, *, into: safepaths.SafePath) -> SourceBundle: ...

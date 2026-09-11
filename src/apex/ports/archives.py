"""Deterministic source bundles.

The archive is the input a build is reproduced from, so its digest must depend on the files
and on nothing else: not on the order the filesystem returned them, not on when they were
last written.

Every candidate passes through a screen before it is written. The screen is the caller's
rule, so the port cannot bundle a file the repository rules refuse, and a refusal leaves no
archive behind.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from typing import Protocol

from apex.kernel import claims, identifiers, quantities, safepaths


@dataclasses.dataclass(frozen=True, slots=True)
class SourceSet:
    root: safepaths.SourceRoot
    relative_paths: tuple[str, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class BundleCandidate:
    path: str
    mode: quantities.FileMode
    payload: bytes


@dataclasses.dataclass(frozen=True, slots=True)
class BundledFile:
    path: str
    mode: quantities.FileMode
    digest: identifiers.Digest


@dataclasses.dataclass(frozen=True, slots=True)
class SourceBundle:
    archive: safepaths.SafePath
    archive_digest: identifiers.Digest
    files: tuple[BundledFile, ...]
    merkle_root: identifiers.MerkleRoot
    reads: int


type Screen = Callable[[BundleCandidate], None]


def admit_all(candidate: BundleCandidate) -> None:
    """The screen that refuses nothing. Only a test has a reason to bundle unscreened."""


class ArchivePort(Protocol):
    environment: claims.EnvironmentKind

    def bundle(
        self, sources: SourceSet, *, into: safepaths.SafePath, screen: Screen
    ) -> SourceBundle: ...

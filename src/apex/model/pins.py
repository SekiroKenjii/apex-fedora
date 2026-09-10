"""Integrity that must be reviewed.

A pinned artifact holds a coordinate and a hash. It has no rule for rendering a URL, so
changing the target release cannot silently change what is downloaded, and a pin is not a
place to record a value that could simply be observed.
"""

from __future__ import annotations

import dataclasses
import enum

from apex.kernel import identifiers


class VerificationLevel(enum.StrEnum):
    TLS_ONLY = "tls-only"
    CHECKSUM = "checksum"
    SIGNED = "signed"

    @property
    def is_cryptographically_bound(self) -> bool:
        return self is not VerificationLevel.TLS_ONLY


@dataclasses.dataclass(frozen=True, slots=True)
class ArchiveCoordinate:
    project: str
    version: str
    filename: str

    def path(self) -> str:
        return f"{self.project}/{self.version}/{self.filename}"


@dataclasses.dataclass(frozen=True, slots=True)
class ReviewRecord:
    reviewer: str
    date: str


@dataclasses.dataclass(frozen=True, slots=True)
class PinnedArtifact:
    coordinate: ArchiveCoordinate
    sha256: identifiers.Digest
    verification: VerificationLevel
    reviewed: ReviewRecord

    def url(self, *, base: str) -> str:
        return f"{base.rstrip('/')}/{self.coordinate.path()}"

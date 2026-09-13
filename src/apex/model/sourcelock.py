"""The reviewed source lock as types.

Every image reference is pinned to its own digest, every archive has a checksum and an https
address, and every filename is a plain basename. The whole document is checked before a single
byte is fetched, so a malformed lock never costs a network request.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from typing import Self

from apex.kernel import errors, identifiers, locators, refusals

SCHEMA = 1
IMAGE_NAMES = ("base", "image_builder")
DEFAULT_ARCHIVE_SUFFIX = ".tar.gz"
PREFIXED_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
HEX_DIGEST = re.compile(r"[0-9a-f]{64}")
OBJECT_ID = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
PINNED_REFERENCE = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}")


@dataclasses.dataclass(frozen=True, slots=True)
class LockedImage:
    name: str
    reference: str
    digest: identifiers.Digest

    @classmethod
    def parse(cls, name: str, entry: object) -> Self:
        if not isinstance(entry, Mapping):
            raise errors.Refusal(refusals.RefusalReason.LOCK_IMAGE_MISSING, subject=name)
        digest = entry.get("digest")
        if not isinstance(digest, str) or not PREFIXED_DIGEST.fullmatch(digest):
            raise errors.Refusal(refusals.RefusalReason.LOCK_IMAGE_DIGEST_MALFORMED, subject=name)
        reference = entry.get("reference")
        if (
            not isinstance(reference, str)
            or not PINNED_REFERENCE.fullmatch(reference)
            or not reference.endswith(f"@{digest}")
        ):
            raise errors.Refusal(
                refusals.RefusalReason.LOCK_IMAGE_REFERENCE_MUTABLE,
                subject=name,
                remedy="pin the reference to the same digest the lock records",
            )
        return cls(name=name, reference=reference, digest=identifiers.Digest.parse(digest))


@dataclasses.dataclass(frozen=True, slots=True)
class LockedSource:
    name: str
    url: locators.HttpsUrl
    sha256: identifiers.Digest
    filename: locators.Basename
    commit: str | None

    @classmethod
    def parse(cls, name: object, entry: object) -> Self:
        if not isinstance(name, str) or not isinstance(entry, Mapping):
            raise errors.Refusal(refusals.RefusalReason.LOCK_ENTRY_MALFORMED, subject=str(name))
        checksum = entry.get("sha256")
        if not isinstance(checksum, str) or not HEX_DIGEST.fullmatch(checksum):
            raise errors.Refusal(refusals.RefusalReason.LOCK_CHECKSUM_MALFORMED, subject=name)
        commit = entry.get("commit")
        if commit is not None and (not isinstance(commit, str) or not OBJECT_ID.fullmatch(commit)):
            raise errors.Refusal(
                refusals.RefusalReason.LOCK_COMMIT_NOT_OBJECT_ID,
                subject=name,
                remedy="name a full commit object id, never a branch or tag",
            )
        filename = entry.get("filename", f"{name}{DEFAULT_ARCHIVE_SUFFIX}")
        return cls(
            name=name,
            url=locators.HttpsUrl(str(entry.get("url", ""))),
            sha256=identifiers.Digest(checksum),
            filename=locators.Basename(str(filename)),
            commit=commit,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class SourceLock:
    images: tuple[LockedImage, ...]
    sources: tuple[LockedSource, ...]


def _sources(document: Mapping[str, object]) -> tuple[LockedSource, ...]:
    listed = document.get("sources")
    if not isinstance(listed, Mapping) or not listed:
        raise errors.Refusal(refusals.RefusalReason.LOCK_SOURCES_EMPTY, subject="sources")
    parsed = tuple(LockedSource.parse(name, entry) for name, entry in listed.items())
    seen: set[str] = set()
    for source in parsed:
        if str(source.filename) in seen:
            raise errors.Refusal(
                refusals.RefusalReason.LOCK_FILENAME_DUPLICATE, subject=str(source.filename)
            )
        seen.add(str(source.filename))
    return parsed


def parse(document: object) -> SourceLock:
    if not isinstance(document, Mapping):
        raise errors.Refusal(refusals.RefusalReason.LOCK_SCHEMA_UNSUPPORTED, subject="lock")
    schema = document.get("schema")
    if isinstance(schema, bool) or schema != SCHEMA:
        raise errors.Refusal(refusals.RefusalReason.LOCK_SCHEMA_UNSUPPORTED, subject=str(schema))
    images = tuple(LockedImage.parse(name, document.get(name)) for name in IMAGE_NAMES)
    return SourceLock(images=images, sources=_sources(document))

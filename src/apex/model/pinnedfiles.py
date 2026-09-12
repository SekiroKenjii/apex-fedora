"""A reviewed set of files pinned by digest under one https base, such as upstream tests.

Every name is a relative path of plain components, every digest is a full hex sha256 and
the base is https by type, so a malformed document is refused before a byte is fetched. The
address of a file is the base followed by its name, exactly as the reviewer wrote them.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping
from typing import Self

from apex.kernel import errors, identifiers, locators, refusals

HEX_DIGEST = re.compile(r"[0-9a-f]{64}")
SEPARATOR = "/"


@dataclasses.dataclass(frozen=True, slots=True)
class PinnedFile:
    name: str
    sha256: identifiers.Digest

    @classmethod
    def parse(cls, name: object, checksum: object) -> Self:
        if not isinstance(name, str) or not name:
            raise errors.Refusal(refusals.RefusalReason.LOCK_ENTRY_MALFORMED, subject=str(name))
        for component in name.split(SEPARATOR):
            locators.Basename(component)
        if not isinstance(checksum, str) or not HEX_DIGEST.fullmatch(checksum):
            raise errors.Refusal(refusals.RefusalReason.LOCK_CHECKSUM_MALFORMED, subject=name)
        return cls(name=name, sha256=identifiers.Digest(checksum))

    def url(self, base: locators.HttpsUrl) -> locators.HttpsUrl:
        return locators.HttpsUrl(f"{base}{self.name}")


@dataclasses.dataclass(frozen=True, slots=True)
class PinnedFileSet:
    version: str
    base: locators.HttpsUrl
    files: tuple[PinnedFile, ...]

    @property
    def names(self) -> frozenset[str]:
        return frozenset(item.name for item in self.files)


def parse(document: object) -> PinnedFileSet:
    if not isinstance(document, Mapping):
        raise errors.Refusal(refusals.RefusalReason.LOCK_SCHEMA_UNSUPPORTED, subject="lock")
    version = document.get("version")
    if not isinstance(version, str) or not version:
        raise errors.Refusal(refusals.RefusalReason.LOCK_ENTRY_MALFORMED, subject="version")
    base = locators.HttpsUrl(str(document.get("base_url", "")))
    listed = document.get("files")
    if not isinstance(listed, Mapping) or not listed:
        raise errors.Refusal(refusals.RefusalReason.LOCK_SOURCES_EMPTY, subject="files")
    files = tuple(PinnedFile.parse(name, checksum) for name, checksum in listed.items())
    return PinnedFileSet(version=version, base=base, files=files)

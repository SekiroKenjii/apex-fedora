"""Which version of the store is on disk, as a value rather than a branch.

Absence of the mark is one of three answers, not a fallback. A mark that exists but cannot be
read is its own inhabitant, so corruption can never be mistaken for the oldest version and
handed to a reader that does not understand the store it is holding.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from apex.kernel import errors, refusals

MARK_NAME = "schema.json"
MARK_BYTE_LIMIT = 4096
FIRST_VERSION = 1
SCHEMA_KEY = "schema"
VERSION_KEY = "version"


@dataclasses.dataclass(frozen=True, slots=True)
class Unmarked:
    """No mark on disk, which the project defines as version one."""


@dataclasses.dataclass(frozen=True, slots=True)
class Marked:
    version: int

    def __post_init__(self) -> None:
        if self.version < FIRST_VERSION:
            raise errors.Refusal(
                refusals.RefusalReason.MALFORMED_STORE_MARK, subject=str(self.version)
            )


@dataclasses.dataclass(frozen=True, slots=True)
class Unreadable:
    detail: str


type VersionMark = Unmarked | Marked | Unreadable


def _version_of(document: object) -> VersionMark:
    if not isinstance(document, dict):
        return Unreadable("the mark is not an object")
    raw = document.get(SCHEMA_KEY, document.get(VERSION_KEY))
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < FIRST_VERSION:
        return Unreadable(f"{raw!r} is not a version")
    return Marked(raw)


def read_mark(runtime_root: Path) -> VersionMark:
    """Answer from the mark alone. Nothing here writes, and nothing repairs.

    The symlink test comes first because `is_file` follows links, and a mark pointing outside
    the root would let another file decide how this whole store is read.
    """
    mark = runtime_root / MARK_NAME
    if mark.is_symlink():
        return Unreadable("the mark is a symbolic link")
    if not mark.exists():
        return Unmarked()
    if not mark.is_file():
        return Unreadable("the mark is not a regular file")
    if mark.stat().st_size > MARK_BYTE_LIMIT:
        return Unreadable(f"the mark is larger than {MARK_BYTE_LIMIT} bytes")
    try:
        return _version_of(json.loads(mark.read_bytes()))
    except json.JSONDecodeError as error:
        return Unreadable(error.msg)

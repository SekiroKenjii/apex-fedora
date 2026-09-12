"""Reading the reviewed source lock out of the checkout.

The lock is a reviewed input. It is read where it lies, refused when it is absent, a link or
unreadable, and never written or recreated by anything in this package.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from apex.kernel import errors, refusals, safepaths
from apex.model import sourcelock

LOCK_PATH = Path("config") / "sources.lock.json"


@dataclasses.dataclass(frozen=True, slots=True)
class ReviewedLock:
    lock: sourcelock.SourceLock
    document: bytes


def reviewed_document(candidate: Path) -> tuple[bytes, object]:
    """A reviewed lock's bytes and the value they hold; absent, linked or unreadable is refused."""
    if candidate.is_symlink():
        raise errors.Refusal(refusals.RefusalReason.PATH_IS_A_SYMLINK, subject=str(candidate))
    if not candidate.is_file():
        raise errors.Refusal(
            refusals.RefusalReason.LOCK_MISSING,
            subject=str(candidate),
            remedy="restore the reviewed lock; nothing recreates it",
        )
    document = candidate.read_bytes()
    try:
        parsed: object = json.loads(document)
    except (json.JSONDecodeError, UnicodeDecodeError) as fault:
        raise errors.Refusal(
            refusals.RefusalReason.LOCK_UNREADABLE, subject=str(candidate)
        ) from fault
    return document, parsed


def load(repository: safepaths.SourceRoot) -> ReviewedLock:
    document, parsed = reviewed_document(repository.path / LOCK_PATH)
    return ReviewedLock(lock=sourcelock.parse(parsed), document=document)

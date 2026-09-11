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


def load(repository: safepaths.SourceRoot) -> ReviewedLock:
    candidate = repository.path / LOCK_PATH
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
        parsed = json.loads(document)
    except (json.JSONDecodeError, UnicodeDecodeError) as fault:
        raise errors.Refusal(
            refusals.RefusalReason.LOCK_UNREADABLE, subject=str(candidate)
        ) from fault
    return ReviewedLock(lock=sourcelock.parse(parsed), document=document)

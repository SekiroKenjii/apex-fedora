"""Reading the reviewed builder base image out of the checkout.

The base the builder boots from is a cloud image pinned by digest under an https address,
reviewed like every other lock; a release profile names no hash, so this is where the
image's is kept. It is read where it lies and never written by anything here.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

from apex.config import sourcepins
from apex.kernel import errors, refusals, safepaths
from apex.model import sourcelock

LOCK_PATH = Path("config") / "builder-base.lock.json"
ENTRY = "base_image"
SCHEMA = "schema"


@dataclasses.dataclass(frozen=True, slots=True)
class ReviewedBase:
    source: sourcelock.LockedSource
    document: bytes


def load(repository: safepaths.SourceRoot) -> ReviewedBase:
    document, parsed = sourcepins.reviewed_document(repository.path / LOCK_PATH)
    if not isinstance(parsed, Mapping) or parsed.get(SCHEMA) != sourcelock.SCHEMA:
        raise errors.Refusal(refusals.RefusalReason.LOCK_SCHEMA_UNSUPPORTED, subject=str(LOCK_PATH))
    return ReviewedBase(
        source=sourcelock.LockedSource.parse(ENTRY, parsed.get(ENTRY)), document=document
    )

"""Reading the reviewed fingerprint test lock out of the checkout.

The lock pins the upstream test files the fingerprint harness imports. Like the source lock
it is read where it lies and never written or recreated by anything in this package.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from apex.config import sourcepins
from apex.kernel import safepaths
from apex.model import pinnedfiles

LOCK_PATH = Path("config") / "fingerprint-tests.lock.json"


@dataclasses.dataclass(frozen=True, slots=True)
class ReviewedFiles:
    files: pinnedfiles.PinnedFileSet
    document: bytes


def load(repository: safepaths.SourceRoot) -> ReviewedFiles:
    document, parsed = sourcepins.reviewed_document(repository.path / LOCK_PATH)
    return ReviewedFiles(files=pinnedfiles.parse(parsed), document=document)

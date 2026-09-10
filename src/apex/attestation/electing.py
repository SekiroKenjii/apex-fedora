"""Mark to reader, and nothing else.

A corrupt mark is refused rather than degraded to the oldest version, and a mark no reader
claims is a fact about this build rather than a defect in a declaration.
"""

from __future__ import annotations

from pathlib import Path

from apex.attestation import markclaims, readerspecs, storereaders
from apex.kernel import errors, refusals
from apex.model import storemark


def elect(mark: storemark.VersionMark) -> readerspecs.StoreReaderSpec:
    """Seal outside any handler.

    Sealing, adding and looking up all raise the same type. A handler around the lookup would
    catch the duplicate-claim message that names both declaring modules and answer it with
    advice to add a third claimant, so membership is tested rather than caught.
    """
    if isinstance(mark, storemark.Unreadable):
        raise errors.Refusal(
            refusals.RefusalReason.MALFORMED_STORE_MARK,
            subject=f"{storemark.MARK_NAME}: {mark.detail}",
            remedy="absence means version one; corruption means nothing at all",
        )
    registered = storereaders.sealed()
    key = markclaims.key_for(mark)
    if key not in registered:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.STORE_VERSION_NOT_SUPPORTED,
            subject=f"{key}; this build reads {', '.join(sorted(registered))}",
        )
    return registered.lookup(key)


def reader_for(runtime_root: Path) -> readerspecs.StoreReaderSpec:
    return elect(storemark.read_mark(runtime_root))

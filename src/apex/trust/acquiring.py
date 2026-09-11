"""Bringing every locked source into the runtime root, each checked against its pin.

A source already present with the right digest is left alone. One whose bytes no longer match
is fetched again. The reviewed lock is copied beside the sources only after every fetch held,
so a runtime root never records a lock it did not fully satisfy.
"""

from __future__ import annotations

import dataclasses

from apex.config import defaults, sourcepins
from apex.kernel import identifiers, safepaths
from apex.model import sourcelock
from apex.ports import portset

ReviewedLock = sourcepins.ReviewedLock


@dataclasses.dataclass(frozen=True, slots=True)
class AcquiredSource:
    name: str
    filename: str
    digest: identifiers.Digest
    fetched: bool


@dataclasses.dataclass(frozen=True, slots=True)
class Acquisition:
    sources: tuple[AcquiredSource, ...]
    lock_record: identifiers.Digest


def acquire(
    ports: portset.HostPorts, *, reviewed: ReviewedLock, root: safepaths.RuntimeRoot
) -> Acquisition:
    acquired = tuple(_acquire_one(ports, source, root=root) for source in reviewed.lock.sources)
    recorded = ports.files.write_atomic(
        root.child(defaults.LOCK_COPY_NAME), reviewed.document, mode=defaults.RECORD_MODE
    )
    return Acquisition(sources=acquired, lock_record=recorded)


def _acquire_one(
    ports: portset.HostPorts, source: sourcelock.LockedSource, *, root: safepaths.RuntimeRoot
) -> AcquiredSource:
    target = root.child(f"{defaults.SOURCES_DIRECTORY}/{source.filename}")
    if _already_held(ports, target, expected=source.sha256, root=root):
        return AcquiredSource(
            name=source.name, filename=str(source.filename), digest=source.sha256, fetched=False
        )
    digest = ports.downloads.fetch(
        source.url, into=target, expected=source.sha256, deadline=defaults.DOWNLOAD_DEADLINE
    )
    return AcquiredSource(
        name=source.name, filename=str(source.filename), digest=digest, fetched=True
    )


def _already_held(
    ports: portset.HostPorts,
    target: safepaths.SafePath,
    *,
    expected: identifiers.Digest,
    root: safepaths.RuntimeRoot,
) -> bool:
    if not ports.files.exists(target):
        return False
    ports.digests.forget()
    present = safepaths.SafePath.regular_file(target.path, within=root)
    return ports.digests.file(present) == expected

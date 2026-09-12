"""Bringing the pinned upstream test files into the runtime root, each checked against its pin.

A guest never downloads, so the files the fingerprint harness imports are fetched here and
laid out as the harness expects them, with the reviewed lock beside them, so the whole
directory can be carried into the guest as it is. A file already present with the right
digest is left alone, and the lock is recorded only after every file held.
"""

from __future__ import annotations

import dataclasses

from apex.config import defaults, fingerprintpins
from apex.kernel import identifiers, locators, safepaths
from apex.model import pinnedfiles
from apex.ports import portset
from apex.trust import acquiring


@dataclasses.dataclass(frozen=True, slots=True)
class AcquiredFile:
    name: str
    digest: identifiers.Digest
    fetched: bool


@dataclasses.dataclass(frozen=True, slots=True)
class Acquired:
    directory: safepaths.SafePath
    files: tuple[AcquiredFile, ...]
    lock_record: identifiers.Digest


def sources_directory(root: safepaths.RuntimeRoot) -> safepaths.SafePath:
    return root.child(
        f"{defaults.FINGERPRINT_TESTS_DIRECTORY}/{defaults.FINGERPRINT_SOURCES_NAME}"
    )


def lock_copy(root: safepaths.RuntimeRoot) -> safepaths.SafePath:
    return root.child(
        f"{defaults.FINGERPRINT_TESTS_DIRECTORY}/{defaults.FINGERPRINT_LOCK_DIRECTORY}/"
        f"{defaults.FINGERPRINT_LOCK_NAME}"
    )


def acquire(
    ports: portset.HostPorts,
    *,
    reviewed: fingerprintpins.ReviewedFiles,
    root: safepaths.RuntimeRoot,
) -> Acquired:
    acquired = tuple(
        _acquire_one(ports, item, base=reviewed.files.base, root=root)
        for item in reviewed.files.files
    )
    recorded = ports.files.write_atomic(
        lock_copy(root), reviewed.document, mode=defaults.RECORD_MODE
    )
    return Acquired(
        directory=root.child(defaults.FINGERPRINT_TESTS_DIRECTORY),
        files=acquired,
        lock_record=recorded,
    )


def _acquire_one(
    ports: portset.HostPorts,
    item: pinnedfiles.PinnedFile,
    *,
    base: locators.HttpsUrl,
    root: safepaths.RuntimeRoot,
) -> AcquiredFile:
    target = root.child(
        f"{defaults.FINGERPRINT_TESTS_DIRECTORY}/{defaults.FINGERPRINT_SOURCES_NAME}/{item.name}"
    )
    if acquiring.already_held(ports, target, expected=item.sha256, root=root):
        return AcquiredFile(name=item.name, digest=item.sha256, fetched=False)
    digest = ports.downloads.fetch(
        item.url(base), into=target, expected=item.sha256, deadline=defaults.DOWNLOAD_DEADLINE
    )
    return AcquiredFile(name=item.name, digest=digest, fetched=True)

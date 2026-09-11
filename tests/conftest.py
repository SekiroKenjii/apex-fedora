"""A whole host bundle made of fakes, so a pipeline can run without touching anything."""

from __future__ import annotations

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_digesting,
    fake_files,
    fake_ids,
    fake_locking,
    fake_process,
)
from apex.ports import portset


def fake_bundle() -> portset.HostPorts:
    return portset.HostPorts(
        processes=fake_process.ScriptedProcess(),
        files=fake_files.MemoryFiles(),
        clock=fake_clock.ManualClock(),
        identities=fake_ids.SequenceIdentities(),
        locks=fake_locking.MemoryLocks(),
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
    )


@pytest.fixture
def ports() -> portset.HostPorts:
    return fake_bundle()

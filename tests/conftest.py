"""A whole host bundle made of fakes, so a pipeline can run without touching anything."""

from __future__ import annotations

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_digesting,
    fake_downloading,
    fake_files,
    fake_guestshell,
    fake_hypervisor,
    fake_ids,
    fake_locking,
    fake_process,
    fake_qmp,
    fake_signing,
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
        signing=fake_signing.FakeSigner(),
        downloads=fake_downloading.OfflineFetcher({}),
        hypervisor=fake_hypervisor.FakeQemu(),
        monitor=fake_qmp.ScriptedQmp(),
        guest=fake_guestshell.ScriptedGuest(),
    )


@pytest.fixture
def ports() -> portset.HostPorts:
    return fake_bundle()

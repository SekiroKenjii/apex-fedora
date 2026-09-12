"""The fixture that builds the bundle of fakes for the machine tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from machinehost import Host

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_digesting,
    fake_downloading,
    fake_files,
    fake_hypervisor,
    fake_ids,
    fake_locking,
    fake_process,
    fake_qmp,
    fake_signing,
)
from apex.kernel import safepaths
from apex.ports import portset


@pytest.fixture
def host(tmp_path: Path) -> Host:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    hypervisor = fake_hypervisor.FakeQemu()
    monitor = fake_qmp.ScriptedQmp({"system_powerdown": {}})
    clock = fake_clock.ManualClock()
    files = fake_files.MemoryFiles()
    processes = fake_process.ScriptedProcess()
    locks = fake_locking.MemoryLocks()
    ports = portset.HostPorts(
        processes=processes,
        files=files,
        clock=clock,
        identities=fake_ids.SequenceIdentities(),
        locks=locks,
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        signing=fake_signing.FakeSigner(),
        downloads=fake_downloading.OfflineFetcher({}),
        hypervisor=hypervisor,
        monitor=monitor,
    )
    return Host(
        ports=ports,
        root=safepaths.RuntimeRoot.adopt(base),
        hypervisor=hypervisor,
        monitor=monitor,
        clock=clock,
        files=files,
        processes=processes,
        locks=locks,
    )

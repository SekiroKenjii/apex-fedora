"""Bundles of every adapter, real and fake, for the port tests."""

from __future__ import annotations

from pathlib import Path

import pytest

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
from apex.adapters.real import (
    real_archives,
    real_clock,
    real_digesting,
    real_downloading,
    real_files,
    real_hypervisor,
    real_ids,
    real_locking,
    real_process,
    real_qmp,
    real_signing,
)
from apex.kernel import safepaths
from apex.ports import portset


@pytest.fixture
def ports_of_fakes() -> portset.HostPorts:
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
    )


@pytest.fixture
def ports_of_reals(tmp_path: Path) -> portset.HostPorts:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return portset.HostPorts(
        processes=real_process.SubprocessRunner(),
        files=real_files.LocalFiles(),
        clock=real_clock.SystemClock(),
        identities=real_ids.RandomIdentities(),
        locks=real_locking.FileLocks(safepaths.RuntimeRoot.adopt(base)),
        digests=real_digesting.CachedDigests(),
        archives=real_archives.TarArchives(),
        signing=real_signing.OpensslSigner(),
        downloads=real_downloading.CurlDownloads(),
        hypervisor=real_hypervisor.QemuHypervisor(),
        monitor=real_qmp.UnixQmp(),
    )

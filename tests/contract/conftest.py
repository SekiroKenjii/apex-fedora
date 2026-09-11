"""One behavioural specification, run against the real adapter and against the fake.

A fake that passes a suite the real adapter also passes cannot drift silently. Where a
property can only hold for one of them, the test says which and why.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_digesting,
    fake_downloading,
    fake_files,
    fake_ids,
    fake_locking,
    fake_process,
    fake_signing,
)
from apex.adapters.real import (
    real_archives,
    real_clock,
    real_digesting,
    real_downloading,
    real_files,
    real_ids,
    real_locking,
    real_process,
    real_signing,
)
from apex.kernel import safepaths


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


@pytest.fixture(params=["real", "fake"])
def processes(request: pytest.FixtureRequest) -> Iterator[object]:
    if request.param == "real":
        yield real_process.SubprocessRunner()
    else:
        yield fake_process.ScriptedProcess.with_shell_probe()


@pytest.fixture(params=["real", "fake"])
def files(request: pytest.FixtureRequest, root: safepaths.RuntimeRoot) -> Iterator[object]:
    if request.param == "real":
        yield real_files.LocalFiles()
    else:
        yield fake_files.MemoryFiles()


@pytest.fixture(params=["real", "fake"])
def identities(request: pytest.FixtureRequest) -> Iterator[object]:
    if request.param == "real":
        yield real_ids.RandomIdentities()
    else:
        yield fake_ids.SequenceIdentities()


@pytest.fixture(params=["real", "fake"])
def clocks(request: pytest.FixtureRequest) -> Iterator[object]:
    if request.param == "real":
        yield real_clock.SystemClock()
    else:
        yield fake_clock.ManualClock()


@pytest.fixture(params=["real", "fake"])
def locks(request: pytest.FixtureRequest, root: safepaths.RuntimeRoot) -> Iterator[object]:
    if request.param == "real":
        yield real_locking.FileLocks(root)
    else:
        yield fake_locking.MemoryLocks()


@pytest.fixture(params=["real", "fake"])
def archives(request: pytest.FixtureRequest) -> Iterator[object]:
    if request.param == "real":
        yield real_archives.TarArchives()
    else:
        yield fake_archives.MemoryArchives()


@pytest.fixture(params=["real", "fake"])
def digests(request: pytest.FixtureRequest) -> Iterator[object]:
    if request.param == "real":
        yield real_digesting.CachedDigests()
    else:
        yield fake_digesting.CountingDigests()


@pytest.fixture(params=["real", "fake"])
def signers(request: pytest.FixtureRequest) -> Iterator[object]:
    if request.param == "real":
        if shutil.which("openssl") is None:
            pytest.skip("NOT TESTED: openssl is absent")
        yield real_signing.OpensslSigner()
    else:
        yield fake_signing.FakeSigner()


@pytest.fixture(params=["real", "fake"])
def downloads(request: pytest.FixtureRequest) -> Iterator[object]:
    if request.param == "real":
        if shutil.which("curl") is None:
            pytest.skip("NOT TESTED: curl is absent")
        yield real_downloading.CurlDownloads()
    else:
        yield fake_downloading.OfflineFetcher({})

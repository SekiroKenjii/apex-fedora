"""One behavioural specification, run against the real adapter and against the fake.

A fake that passes a suite the real adapter also passes cannot drift silently. Where a
property can only hold for one of them, the test says which and why.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from apex.adapters.fakes import fake_clock, fake_files, fake_ids, fake_process
from apex.adapters.real import real_clock, real_files, real_ids, real_process
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

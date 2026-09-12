"""Both ways of reaching the process descriptor calls behave the same."""

from __future__ import annotations

import os
import signal
import subprocess
import sys

import pytest

from apex.adapters import pidfds


@pytest.fixture(params=["module", "syscall"], autouse=True)
def route(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test runs once through `os` and once through the direct system calls."""
    if request.param == "syscall":
        monkeypatch.delattr(os, "pidfd_open", raising=False)
    elif not hasattr(os, "pidfd_open"):
        pytest.skip("NOT TESTED: this interpreter has no os.pidfd_open")


def test_a_descriptor_names_a_live_process() -> None:
    descriptor = pidfds.open_process(os.getpid())
    try:
        assert os.fstat(descriptor).st_ino > 0
        pidfds.send_signal(descriptor, 0)
    finally:
        os.close(descriptor)


def test_a_process_that_is_gone_is_an_os_error() -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    child.wait()

    with pytest.raises(OSError):
        pidfds.open_process(child.pid)


def test_a_signal_reaches_the_process_the_descriptor_names() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])  # noqa: S603
    descriptor = pidfds.open_process(child.pid)
    try:
        pidfds.send_signal(descriptor, signal.SIGKILL)
    finally:
        os.close(descriptor)

    assert child.wait(timeout=5) == -signal.SIGKILL

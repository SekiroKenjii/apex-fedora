"""One behavioural specification, run against the real adapter and against the fake.

A fake that passes a suite the real adapter also passes cannot drift silently. Where a
property can only hold for one of them, the test says which and why.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import socket
import stat
import sys
import threading
from collections.abc import Iterator
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
from apex.model import machines
from apex.ports import qmp

# A stand-in for the hypervisor: it opens the monitor socket it was told to and then waits,
# which is all the process mechanics of the real adapter need from it.
QEMU_SHIM = f"""#!{sys.executable}
import os, socket, sys, time
arguments = sys.argv[1:]
option = arguments[arguments.index("-qmp") + 1]
path = option.split(":", 1)[1].split(",")[0]
if os.environ.get("APEX_SHIM_EXIT"):
    sys.exit(3)
listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
listener.bind(path)
listener.listen(1)
time.sleep(30)
"""

MONITOR_REPLIES: dict[str, object] = {
    "qmp_capabilities": {},
    "query-status": {"status": "running"},
    "system_powerdown": {},
}


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


@pytest.fixture(params=["real", "fake"])
def hypervisors(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[object]:
    if request.param == "real":
        shims = tmp_path / "bin"
        shims.mkdir()
        shim = shims / machines.QEMU_PROGRAM
        shim.write_text(QEMU_SHIM)
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setenv("PATH", f"{shims}:{request.config.getoption('--basetemp', '')}")
        yield real_hypervisor.QemuHypervisor()
    else:
        yield fake_hypervisor.FakeQemu()


@dataclasses.dataclass(frozen=True, slots=True)
class Monitor:
    port: qmp.QmpPort
    socket: safepaths.SafePath


def _serve_monitor(path: Path, ready: threading.Event) -> None:
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(1)
    ready.set()
    connection, _ = listener.accept()
    with connection, connection.makefile("rwb") as stream:
        stream.write(b'{"QMP": {"version": {}, "capabilities": []}}\n')
        stream.flush()
        for line in stream:
            request = json.loads(line)
            name, identifier = request["execute"], request.get("id")
            if name == "quit":
                break
            if name == "query-status":
                stream.write(b'{"event": "RESUME", "timestamp": {"seconds": 1}}\n')
            if name in MONITOR_REPLIES:
                reply: dict[str, object] = {"return": MONITOR_REPLIES[name], "id": identifier}
            else:
                reply = {
                    "error": {"class": "CommandNotFound", "desc": f"{name} has not been found"},
                    "id": identifier,
                }
            stream.write(json.dumps(reply).encode() + b"\n")
            stream.flush()
    listener.close()


@pytest.fixture(params=["real", "fake"])
def monitors(request: pytest.FixtureRequest, root: safepaths.RuntimeRoot) -> Iterator[Monitor]:
    path = root.child("qmp.sock")
    if request.param == "real":
        ready = threading.Event()
        server = threading.Thread(target=_serve_monitor, args=(path.path, ready), daemon=True)
        server.start()
        ready.wait(timeout=5)
        yield Monitor(port=real_qmp.UnixQmp(), socket=path)
    else:
        yield Monitor(port=fake_qmp.ScriptedQmp(MONITOR_REPLIES), socket=path)

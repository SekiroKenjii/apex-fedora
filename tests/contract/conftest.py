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
    fake_containers,
    fake_digesting,
    fake_downloading,
    fake_extents,
    fake_files,
    fake_guestshell,
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
    real_containers,
    real_digesting,
    real_downloading,
    real_extents,
    real_files,
    real_guestshell,
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

# Stand-ins for ssh and scp. The ssh shim prints the script it was handed; the scp shim copies
# between the host and a directory standing for the guest's filesystem.
SSH_SHIM = f"""#!{sys.executable}
import sys
sys.stdout.write(sys.argv[-1])
sys.stdout.flush()
sys.stdout.buffer.write(sys.stdin.buffer.read())
"""
SCP_SHIM = f"""#!{sys.executable}
import os, shutil, sys
root = os.environ["APEX_SHIM_GUEST_ROOT"]
arguments = sys.argv[1:]
positional = []
skip = False
for item in arguments:
    if skip:
        skip = False
        continue
    if item in ("-i", "-P", "-o"):
        skip = True
        continue
    if item.startswith("-"):
        continue
    positional.append(item)
source, destination = positional[-2], positional[-1]
def resolve(spec):
    return root + spec.split(":", 1)[1] if "@127.0.0.1:" in spec else spec
source, destination = resolve(source), resolve(destination)
os.makedirs(os.path.dirname(destination.rstrip("/")) or ".", exist_ok=True)
if os.path.isdir(source):
    if os.path.isdir(destination):
        destination = os.path.join(destination, os.path.basename(source.rstrip("/")))
    shutil.copytree(source, destination)
else:
    shutil.copy(source, destination)
"""

# A stand-in for both engine programs: it answers the queries the contract suite makes about
# one image and accepts every build, copy and key generation.
ENGINE_SHIM = f"""#!{sys.executable}
import sys
arguments = sys.argv[1:]
program = sys.argv[0].rsplit("/", 1)[-1]
if program == "podman" and arguments[:2] == ["image", "inspect"]:
    name = arguments[-1]
    if name != "localhost/apex:fedora":
        sys.stderr.write("Error: no such image\\n")
        sys.exit(125)
    formatted = "--format" in arguments
    sys.stdout.write("sha256:" + "a" * 64 + "\\n" if formatted else '{{"config": {{}}}}')
elif program == "podman" and arguments[:1] == ["run"]:
    tail = arguments[arguments.index("localhost/apex:fedora") + 1:]
    if tail == ["false"]:
        sys.exit(1)
    sys.stdout.write("bash-5\\n")
elif program == "podman" and arguments[:1] == ["ps"]:
    sys.stdout.write("[]")
elif program == "skopeo" and arguments[:2] == ["inspect", "--raw"]:
    if "localhost/apex:fedora" not in arguments[-1]:
        sys.stderr.write("Error: no such image\\n")
        sys.exit(1)
    sys.stdout.write('{{"schemaVersion": 2}}')
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


@pytest.fixture(params=["real", "fake"])
def guests(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[object]:
    if request.param == "real":
        shims = tmp_path / "shims"
        shims.mkdir()
        for name, body in (("ssh", SSH_SHIM), ("scp", SCP_SHIM)):
            shim = shims / name
            shim.write_text(body)
            shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
        guest_root = tmp_path / "guest"
        guest_root.mkdir()
        monkeypatch.setenv("PATH", f"{shims}:{request.config.getoption('--basetemp', '')}")
        monkeypatch.setenv("APEX_SHIM_GUEST_ROOT", str(guest_root))
        yield real_guestshell.OpensshGuestShell(real_process.SubprocessRunner())
    else:
        yield fake_guestshell.ScriptedGuest.echoing()


@pytest.fixture(params=["real", "fake"])
def engines(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[object]:
    if request.param == "real":
        shims = tmp_path / "engine-shims"
        shims.mkdir()
        for name in ("podman", "skopeo"):
            shim = shims / name
            shim.write_text(ENGINE_SHIM)
            shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setenv("PATH", f"{shims}:{request.config.getoption('--basetemp', '')}")
        yield real_containers.PodmanEngine(real_process.SubprocessRunner())
    else:
        yield fake_containers.FakeRegistry.with_shell_probe()


@pytest.fixture(params=["real", "fake"])
def shares(request: pytest.FixtureRequest) -> Iterator[object]:
    if request.param == "real":
        yield real_extents.LinuxExtents()
    else:
        yield fake_extents.FakeExtents()

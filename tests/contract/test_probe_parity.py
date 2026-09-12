"""The observation units and the older probe scripts read the same things.

Each older script runs with every program answered and every file it opens recorded. The
unit runs on a scripted process and a recording tree with the same answers. The argument
vectors must agree in order, and every file the older script read must be read by the unit.
The unit reads the block tree through one snapshot, so it may read more attributes than the
script; it may never read fewer.
"""

from __future__ import annotations

import importlib.util
import pathlib
import types
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_blockdevices,
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_extents,
    fake_files,
    fake_ids,
    fake_process,
)
from apex.agent import agentports, guestguard
from apex.agent.units import live_observe_unit, ventoy_observe_unit
from apex.config import defaults
from apex.kernel import quantities, safepaths

REPOSITORY = Path(__file__).resolve().parents[2]
SYSFS = "/sys/class/block"
DEVICE_HOME = "/sys/devices/pci0000:00/0000:00:04.0/virtio1/block/vda"
CMDLINE = f"BOOT_IMAGE=/vmlinuz {defaults.LIVE_ROOT_TOKEN} quiet\n"
CANNED = {
    "/proc/cmdline": CMDLINE,
    "/proc/swaps": "Filename\n",
    "/etc/os-release": "ID=fedora\n",
}
PUBLIC = quantities.FileMode(0o444)


class Recording(fake_files.MemoryFiles):
    def __init__(self) -> None:
        super().__init__()
        self.read: list[str] = []

    def read_bytes(self, path: safepaths.SafePath, *, limit: int) -> bytes:
        self.read.append(str(path))
        return super().read_bytes(path, limit=limit)

    def inspect(self, path: safepaths.SafePath) -> Any:
        self.read.append(str(path))
        return super().inspect(path)


def older_module(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPOSITORY / "guest" / name
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def older_sysfs(tmp_path: Path) -> Path:
    """A tree shaped like sysfs, on disk, for the older script's `iterdir` and `resolve`."""
    root = tmp_path / SYSFS.lstrip("/")
    root.mkdir(parents=True)
    home = tmp_path / DEVICE_HOME.lstrip("/")
    for name, number, partition in (("vda", "253:0", None), ("vda1", "253:1", 1)):
        target = home if partition is None else home / name
        target.mkdir(parents=True, exist_ok=True)
        (target / "dev").write_text(f"{number}\n")
        (target / "ro").write_text("1\n")
        (target / "size").write_text("8388608\n")
        (target / "holders").mkdir()
        if partition is None:
            (target / "serial").write_text("apex-other-1\n")
            (target / "slaves").mkdir()
        else:
            (target / "partition").write_text(f"{partition}\n")
        (root / name).symlink_to(target)
    return root


def newer_tree() -> Recording:
    files = Recording()
    for name, text in CANNED.items():
        files.write_atomic(safepaths.SafePath(Path(name)), text.encode(), mode=PUBLIC)
    files.make_directory(safepaths.SafePath(Path(SYSFS)), mode=PUBLIC)
    home = safepaths.SafePath(Path(DEVICE_HOME))
    for name, number, partition in (("vda", "253:0", None), ("vda1", "253:1", 1)):
        target = home if partition is None else home / name
        files.write_atomic(target / "dev", f"{number}\n".encode(), mode=PUBLIC)
        files.write_atomic(target / "ro", b"1\n", mode=PUBLIC)
        files.write_atomic(target / "size", b"8388608\n", mode=PUBLIC)
        files.make_directory(target / "holders", mode=PUBLIC)
        if partition is None:
            files.write_atomic(target / "serial", b"apex-other-1\n", mode=PUBLIC)
            files.make_directory(target / "slaves", mode=PUBLIC)
        else:
            files.write_atomic(target / "partition", f"{partition}\n".encode(), mode=PUBLIC)
        files.symlink(safepaths.SafePath(Path(SYSFS)) / name, target=target)
    return files


class Answering(fake_process.ScriptedProcess):
    def run(self, argv: Any, **keywords: Any) -> Any:
        self.expect(tuple(argv), fake_process.Reply(stdout=answer(list(argv))))
        return super().run(argv, **keywords)


def answer(argv: list[str]) -> bytes:
    return b"kvm\n" if argv[0] == "systemd-detect-virt" else b""


def bundle(files: Recording) -> tuple[Answering, agentports.AgentPorts]:
    process = Answering()
    ports = agentports.AgentPorts(
        processes=process, files=files, clock=fake_clock.ManualClock(),
        containers=fake_containers.FakeRegistry(), digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(), identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(), blocks=fake_blockdevices.FakeBlockDevices(),
    )
    return process, ports


def unprefixed(path: str, tmp_path: Path) -> str:
    return "/" + str(Path(path).relative_to(tmp_path)) if path.startswith(str(tmp_path)) else path


def patch_older(
    module: types.ModuleType, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[list[list[str]], list[str]]:
    calls: list[list[str]] = []
    read: list[str] = []
    original_read_text = pathlib.Path.read_text

    def run(argv: list[Any], **_: Any) -> types.SimpleNamespace:
        rendered = [str(item) for item in argv]
        calls.append(rendered)
        return types.SimpleNamespace(
            returncode=0, stdout=answer(rendered).decode(), stderr=""
        )

    def read_text(self: Path, *arguments: Any, **keywords: Any) -> str:
        name = unprefixed(str(self), tmp_path)
        read.append(name)
        if name in CANNED:
            return CANNED[name]
        return original_read_text(self, *arguments, **keywords)

    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    return calls, read


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)


def test_the_live_probe_runs_the_same_programs_and_reads_the_same_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = older_module("live-probe.py")
    calls, read = patch_older(module, monkeypatch, tmp_path)
    sysfs = older_sysfs(tmp_path)
    original_text_file = module.text_file
    original_metadata = module.file_metadata
    original_blocks = module.block_observations

    def text_file(path: Path) -> Any:
        read.append(unprefixed(str(path), tmp_path))
        return original_text_file(path)

    def file_metadata(path: Path) -> Any:
        read.append(unprefixed(str(path), tmp_path))
        return original_metadata(path)

    monkeypatch.setattr(module, "text_file", text_file)
    monkeypatch.setattr(module, "file_metadata", file_metadata)
    monkeypatch.setattr(module, "block_observations", lambda root=sysfs: original_blocks(root))
    module.main()
    capsys.readouterr()

    files = newer_tree()
    process, ports = bundle(files)
    live_observe_unit.run(ports, arguments={})

    newer_calls = [list(call) for call in process.calls]
    assert newer_calls == calls
    assert set(read) <= set(files.read)


def test_the_ventoy_probe_runs_the_same_programs_and_reads_the_same_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = older_module("ventoy-probe.py")
    calls, read = patch_older(module, monkeypatch, tmp_path)
    sysfs = older_sysfs(tmp_path)
    original_blocks = module.block_topology
    monkeypatch.setattr(module, "block_topology", lambda root=sysfs: original_blocks(root))
    module.main()
    capsys.readouterr()

    files = newer_tree()
    process, ports = bundle(files)
    ventoy_observe_unit.run(ports, arguments={})

    newer_calls = [list(call) for call in process.calls]
    assert newer_calls == calls
    assert set(read) <= set(files.read)
    assert f"{SYSFS}/vda/ro" in files.read

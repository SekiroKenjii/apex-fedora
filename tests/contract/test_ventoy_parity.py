"""The unit and the older script prepare the medium with the same commands.

The older script insists on running from a directory under `/var/tmp` named for its run, so
the harness makes one, answers every program it runs, and removes the directory afterwards.
The unit runs from a second such directory on the same answers. The two sequences of argument
vectors, each with the directory the command started in, must agree once the directories are
normalised.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import pathlib
import secrets
import shutil
import tarfile
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import fake_clock, fake_containers, fake_process
from apex.adapters.real import real_archives, real_digesting, real_files
from apex.agent import agentports, builder
from apex.agent.units import ventoy_unit
from apex.config import defaults
from apex.kernel import hashing, quantities

REPOSITORY = Path(__file__).resolve().parents[2]
VERSION = "1.1.05"
TABLE = json.dumps({"partitiontable": {"label": "dos", "partitions": [{"a": 1}, {"b": 2}]}})
VAR_TMP = Path("/var/tmp")


def answer(argv: list[str]) -> str:
    if argv[0] == "systemd-detect-virt":
        return "kvm\n"
    if argv[0] == "losetup" and "--find" in argv:
        return "/dev/loop0\n"
    if argv[:2] == ["sfdisk", "--json"]:
        return TABLE
    if argv[:3] == ["sh", "Ventoy2Disk.sh", "-l"]:
        return f"Ventoy Version in Disk: {VERSION}\n"
    if argv[0] == "rpm":
        return "parted-3\n"
    return ""


def populate(work: Path) -> None:
    packed = work / "ventoy.tar.gz"
    with tarfile.open(packed, "w:gz") as opened:
        member = tarfile.TarInfo(f"ventoy-{VERSION}/ventoy/version")
        member.size = len(VERSION)
        opened.addfile(member, io.BytesIO(VERSION.encode()))
    files = {}
    for name in ("ventoy.tar.gz", "Apex-Live.iso", "Ubuntu.iso"):
        if name != "ventoy.tar.gz":
            (work / name).write_bytes(name.encode())
        files[name] = hashing.digest_bytes((work / name).read_bytes()).hex
    (work / "request.json").write_text(json.dumps({"files": files, "ventoy_version": VERSION}))


@pytest.fixture
def workspaces() -> Iterator[tuple[Path, Path]]:
    if not os.access(VAR_TMP, os.W_OK):
        pytest.skip("NOT TESTED: /var/tmp is not writable here")
    older = VAR_TMP / f"apex-ventoy-{secrets.token_hex(16)}"
    newer = VAR_TMP / f"apex-ventoy-{secrets.token_hex(16)}"
    for work in (older, newer):
        work.mkdir(mode=0o700)
        populate(work)
    try:
        yield older, newer
    finally:
        shutil.rmtree(older, ignore_errors=True)
        shutil.rmtree(newer, ignore_errors=True)


def older_calls(work: Path, monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], str]]:
    spec = importlib.util.spec_from_file_location(
        "ventoy_fixture_script", REPOSITORY / "guest" / "ventoy-fixture.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls: list[tuple[list[str], str]] = []
    original_read_text = pathlib.Path.read_text
    original_digest = module.digest

    def read_text(self: Path, *arguments: Any, **keywords: Any) -> str:
        if str(self) == defaults.BUILDER_MARKER:
            return f"{defaults.BUILDER_MARKER_TEXT}\n"
        if str(self).startswith("/sys/class/block/"):
            return f"{work}/ventoy.raw\n"
        return original_read_text(self, *arguments, **keywords)

    def run(argv: list[Any], **keywords: Any) -> types.SimpleNamespace:
        rendered = [str(item) for item in argv]
        calls.append((rendered, str(keywords.get("cwd", ""))))
        return types.SimpleNamespace(returncode=0, stdout=answer(rendered))

    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    monkeypatch.setattr(pathlib.Path, "is_block_device", lambda self: True)
    monkeypatch.setattr(
        module.shutil, "disk_usage", lambda _path: types.SimpleNamespace(free=100 * 1024**3)
    )
    monkeypatch.setattr(
        module, "digest", lambda path: original_digest(path) if Path(path).exists() else "0" * 64
    )
    monkeypatch.setattr(module.os, "sync", lambda: None)
    monkeypatch.chdir(work)
    module.main()
    return calls


class Answering(fake_process.ScriptedProcess):
    def run(self, argv: Any, **keywords: Any) -> Any:
        if list(argv)[:2] == ["qemu-img", "convert"]:
            Path(list(argv)[-1]).write_bytes(b"qcow2")
        self.expect(tuple(argv), fake_process.Reply(stdout=answer(list(argv)).encode()))
        return super().run(argv, **keywords)


def newer_calls(
    work: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> list[tuple[list[str], str]]:
    process = Answering()
    marker = tmp_path / "apex-builder"
    marker.write_text(f"{defaults.BUILDER_MARKER_TEXT}\n")
    devices = tmp_path / "dev"
    devices.mkdir()
    (devices / "loop0").write_bytes(b"")
    (devices / "loop0p1").write_bytes(b"")
    sysfs = tmp_path / "block" / "loop0" / "loop"
    sysfs.mkdir(parents=True)
    (sysfs / "backing_file").write_text(f"{work}/ventoy.raw\n")
    monkeypatch.setattr(defaults, "BUILDER_MARKER", str(marker))
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    monkeypatch.setattr(ventoy_unit, "BLOCK_CLASS", str(tmp_path / "block"))
    monkeypatch.setattr(ventoy_unit.os, "sync", lambda: None)
    monkeypatch.setattr(
        real_files.LocalFiles, "free_space", lambda self, path: quantities.Gib(100).as_bytes()
    )

    def answering(argv: list[str]) -> bytes:
        text = answer(argv)
        return text.replace("/dev/loop0", f"{devices}/loop0").encode()

    def run(argv: Any, **keywords: Any) -> Any:
        if list(argv)[:2] == ["qemu-img", "convert"]:
            Path(list(argv)[-1]).write_bytes(b"qcow2")
        process.expect(tuple(argv), fake_process.Reply(stdout=answering(list(argv))))
        return fake_process.ScriptedProcess.run(process, argv, **keywords)

    process.run = run  # type: ignore[method-assign]
    monkeypatch.setattr(ventoy_unit, "LOOP", ventoy_unit.re.compile(rf"{devices}/loop[0-9]+"))
    ports = agentports.AgentPorts(
        processes=process,
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        containers=fake_containers.FakeRegistry(),
        digests=real_digesting.CachedDigests(),
        archives=real_archives.TarArchives(),
    )
    ventoy_unit.run(ports, arguments={"work": str(work)})
    calls = []
    for argv, cwd in zip(process.calls, process.directories, strict=True):
        rendered = [item.replace(f"{devices}/loop0", "/dev/loop0") for item in argv]
        calls.append((rendered, "" if cwd is None else str(cwd)))
    return calls


def normalised(calls: list[tuple[list[str], str]], work: Path) -> list[tuple[list[str], str]]:
    return [
        ([item.replace(str(work), "<work>") for item in argv], cwd.replace(str(work), "<work>"))
        for argv, cwd in calls
    ]


def test_the_unit_and_the_older_script_run_the_same_commands(
    workspaces: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    older_work, newer_work = workspaces

    older = normalised(older_calls(older_work, monkeypatch), older_work)
    monkeypatch.undo()
    newer = normalised(newer_calls(newer_work, tmp_path, monkeypatch), newer_work)

    assert newer == older

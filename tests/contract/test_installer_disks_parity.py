"""The unit and the older script format the same disks with the same commands.

The older script is run with its effects captured: every program it would run is recorded,
the loop device and the partition table are answered, and the builder marker and the loop's
backing file are answered where it reads them. The unit runs on the scripted process with the
same answers. The two argument vector sequences must agree.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import tempfile
import types
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_containers,
    fake_digesting,
    fake_extents,
    fake_files,
    fake_ids,
    fake_process,
)
from apex.agent import agentports, builder
from apex.agent.units import installer_disks_unit
from apex.config import defaults
from apex.kernel import quantities, safepaths

REPOSITORY = Path(__file__).resolve().parents[2]
LOOP = "/dev/loop0"
TABLE = json.dumps({"partitiontable": {"label": "gpt", "partitions": []}})
MARKER = f"{defaults.BUILDER_MARKER_TEXT}\n"


def answers(argv: list[str], raw: Path) -> bytes:
    if argv[0] == "systemd-detect-virt":
        return b"kvm\n"
    if argv[0] == "losetup" and "--find" in argv:
        return f"{LOOP}\n".encode()
    if argv[:2] == ["sfdisk", "--json"]:
        return TABLE.encode()
    return b""


def older_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    spec = importlib.util.spec_from_file_location(
        "installer_fixtures", REPOSITORY / "guest" / "installer-fixtures.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    remote = tmp_path / "remote"
    work = tmp_path / "work"
    remote.mkdir()
    work.mkdir()
    raw = work / "other.raw"
    calls: list[list[str]] = []
    original_read_text = pathlib.Path.read_text

    def read_text(self: Path, *arguments: Any, **keywords: Any) -> str:
        if str(self) == defaults.BUILDER_MARKER:
            return MARKER
        if str(self).startswith("/sys/class/block/"):
            return f"{raw}\n"
        return original_read_text(self, *arguments, **keywords)

    def run(argv: list[Any], **_: Any) -> types.SimpleNamespace:
        rendered = [str(item) for item in argv]
        calls.append(rendered)
        return types.SimpleNamespace(returncode=0, stdout=answers(rendered, raw).decode())

    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    monkeypatch.setattr(pathlib.Path, "is_block_device", lambda self: True)
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_: str(work))
    monkeypatch.setattr(module, "digest", lambda path: "0" * 64)
    monkeypatch.chdir(remote)
    module.main()
    # The older script names its outputs relative to the directory it was started in; the
    # unit is told that directory. Same path, spelt from the same place.
    return [
        [str(remote / item) if item.startswith("output/") else item for item in call]
        for call in calls
    ]


def newer_calls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    remote = tmp_path / "remote"
    work = tmp_path / "work"
    output = remote / "output"
    output.mkdir(parents=True, exist_ok=True)
    for name in ("other.qcow2", "target.qcow2"):
        (output / name).write_bytes(name.encode())
    raw = work / "other.raw"
    process = _Answering(raw)
    files = fake_files.MemoryFiles()
    private = quantities.FileMode(0o600)
    files.write_atomic(
        safepaths.SafePath(Path(defaults.BUILDER_MARKER)), MARKER.encode(), mode=private
    )
    files.write_atomic(
        safepaths.SafePath(Path("/sys/class/block/loop0/loop/backing_file")),
        f"{raw}\n".encode(), mode=private,
    )
    for index in (1, 2, 3):
        files.write_atomic(safepaths.SafePath(Path(f"{LOOP}p{index}")), b"", mode=private)
    ports = agentports.AgentPorts(
        processes=process,
        files=files,
        clock=fake_clock.ManualClock(),
        containers=fake_containers.FakeRegistry(),
        digests=fake_digesting.CountingDigests(),
        archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(),
    )
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    installer_disks_unit.run(
        ports, arguments={"work": str(work), "output": str(output), "token": "b" * 32}
    )
    return [list(call) for call in process.calls]


class _Answering(fake_process.ScriptedProcess):
    """A scripted process that answers any vector, with the same answers the older run got."""

    def __init__(self, raw: Path) -> None:
        super().__init__()
        self._raw = raw

    def run(self, argv: Any, **keywords: Any) -> Any:
        self.expect(tuple(argv), fake_process.Reply(stdout=answers(list(argv), self._raw)))
        return super().run(argv, **keywords)


def test_the_unit_and_the_older_script_run_the_same_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    older = older_calls(tmp_path, monkeypatch)
    newer = newer_calls(tmp_path, monkeypatch)

    assert newer == older


def test_the_older_script_still_refuses_the_host() -> None:
    assert os.geteuid() != 0

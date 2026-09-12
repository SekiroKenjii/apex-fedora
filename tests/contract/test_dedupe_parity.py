"""The dedupe unit's self test and the older script's agree on the programs run and the proof.

The kernel call is answered by a stand-in that compares the bytes the descriptors name, for
the older script through its `fcntl` and for the unit through the fake extent port, which
reads the same bytes. Both sides then run the same three checks and prove the same three
properties.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import tempfile
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import (
    fake_archives,
    fake_clock,
    fake_extents,
    fake_ids,
    fake_process,
)
from apex.adapters.real import real_containers, real_digesting, real_files
from apex.agent import agentports, builder
from apex.agent.units import dedupe_unit
from apex.config import defaults
from apex.model import extents

REPOSITORY = Path(__file__).resolve().parents[2]


def answer(argv: list[str]) -> str:
    if argv[0] == "systemd-detect-virt":
        return "kvm\n"
    if argv[0] == "findmnt":
        return "btrfs\n"
    if argv[0] == "podman":
        return "[]"
    return ""


def ioctl(descriptor: int, request: int, buffer: bytearray, mutate: bool = False) -> int:
    """The kernel's answer, from the bytes: shared when equal, differing otherwise."""
    assert request == extents.FIDEDUPERANGE and mutate
    offset, length, _, _, _ = extents.HEADER.unpack_from(buffer, 0)
    target, target_offset, _, _, _ = extents.INFO.unpack_from(buffer, extents.HEADER.size)
    same = os.pread(descriptor, length, offset) == os.pread(target, length, target_offset)
    status = extents.SAME_DATA if same else extents.DIFFERS
    extents.INFO.pack_into(
        buffer, extents.HEADER.size, target, target_offset, length if same else 0, status, 0
    )
    return 0


def older(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[list[str]], dict[str, Any]]:
    spec = importlib.util.spec_from_file_location(
        "dedupe_script", REPOSITORY / "guest" / "dedupe-update-blobs.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    work = tmp_path / "older"
    work.mkdir()
    lock = tmp_path / "lock"
    calls: list[list[str]] = []
    original_read_text = pathlib.Path.read_text
    original_open = pathlib.Path.open

    def read_text(self: Path, *arguments: Any, **keywords: Any) -> str:
        if str(self) == defaults.BUILDER_MARKER:
            return f"{defaults.BUILDER_MARKER_TEXT}\n"
        return original_read_text(self, *arguments, **keywords)

    def opened(self: Path, *arguments: Any, **keywords: Any) -> Any:
        if str(self) == "/run/apex-build.lock":
            return original_open(lock, *arguments, **keywords)
        return original_open(self, *arguments, **keywords)

    def check_output(argv: list[Any], **_: Any) -> str:
        rendered = [str(item) for item in argv]
        calls.append(rendered)
        return answer(rendered)

    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(module.subprocess, "check_output", check_output)
    monkeypatch.setattr(module.fcntl, "ioctl", ioctl)
    monkeypatch.setattr(module.os, "sync", lambda: None)
    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    monkeypatch.setattr(pathlib.Path, "open", opened)
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **_: str(work))
    monkeypatch.setattr("sys.argv", ["dedupe", "--self-test"])
    module.main()
    return calls, json.loads((work / "result.json").read_text())


class Answering(fake_process.ScriptedProcess):
    def run(self, argv: Any, **keywords: Any) -> Any:
        self.expect(tuple(argv), fake_process.Reply(stdout=answer(list(argv)).encode()))
        return super().run(argv, **keywords)


def newer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[list[str]], dict[str, Any]]:
    marker = tmp_path / "apex-builder"
    marker.write_text(f"{defaults.BUILDER_MARKER_TEXT}\n")
    monkeypatch.setattr(defaults, "BUILDER_MARKER", str(marker))
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    monkeypatch.setattr(dedupe_unit.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(dedupe_unit.os, "sync", lambda: None)
    monkeypatch.setattr(dedupe_unit, "WORK_PREFIX", str(tmp_path / "apex-dedupe-"))
    process = Answering()
    ports = agentports.AgentPorts(
        processes=process,
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        containers=real_containers.PodmanEngine(process),
        digests=real_digesting.CachedDigests(),
        archives=fake_archives.MemoryArchives(),
        identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(),
    )
    work = tmp_path / ("apex-dedupe-" + "a" * 32)
    report = dedupe_unit.run(ports, arguments={"work": str(work)})
    return [list(call) for call in process.calls], dict(report)


def test_both_run_the_same_checks_and_prove_the_same_three_things(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    older_calls, older_report = older(tmp_path, monkeypatch)
    monkeypatch.undo()
    newer_calls, newer_report = newer(tmp_path, monkeypatch)

    assert newer_calls == older_calls
    assert newer_report["status"] == older_report["status"] == "PASS"
    assert set(newer_report["self_test"]) == set(older_report["self_test"])
    assert newer_report["self_test"]["kernel_rejected_difference"] is True
    assert newer_report["self_test"]["cow_write_isolation"] is True
    assert (
        newer_report["self_test"]["identical"]["bytes_submitted"]
        == older_report["self_test"]["identical"]["bytes_submitted"]
    )

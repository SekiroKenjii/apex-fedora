"""The diagnostics units collect what the older scripts collected.

The laptop collector is compared on the programs it runs and the codec dumps it reads. The
installer collector is compared on the programs, the logs, and the bundle the older receiver
decodes from the older emitter's frames against the unit's own document.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import types
from pathlib import Path
from typing import Any

import pytest
from diagnosticfixtures import DESTINATION, answering, bundle, installer, laptop

from apex.agent import guestguard
from apex.agent.units import guest_diagnostics_unit, installer_diagnostics_unit
from apex.config import defaults
from apexlib import installerlogs

REPOSITORY = Path(__file__).resolve().parents[2]
TOKEN = "a" * 32


def older(name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        name.replace("-", "_"), REPOSITORY / "guest" / name
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)


def test_the_laptop_collector_runs_the_same_programs_and_reads_the_same_codecs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = older("diagnostics.py")
    asound = tmp_path / "proc" / "asound"
    for name, text in (("card0/codec#0", "Realtek ALC294\n"), ("card1/codec#2", "HDMI\n")):
        (asound / name).parent.mkdir(parents=True, exist_ok=True)
        (asound / name).write_text(text)
    (asound / "card0" / "id").write_text("PCH\n")
    calls: list[list[str]] = []

    def run(argv: list[Any], **_: Any) -> types.SimpleNamespace:
        calls.append([str(item) for item in argv])
        return types.SimpleNamespace(returncode=0, stdout="observed\n", stderr="")

    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module, "Path", lambda name: tmp_path / str(name).lstrip("/"))
    before = module.collect()

    process = answering(*(tuple(argv) for argv in guest_diagnostics_unit.COMMANDS.values()))
    after = guest_diagnostics_unit.run(
        bundle(process, laptop()), arguments={"destination": DESTINATION}
    )

    assert [list(call) for call in process.calls] == calls
    assert set(before["commands"]) == set(after["commands"])  # type: ignore[arg-type]
    older_codecs = {"/" + str(Path(name).relative_to(tmp_path)) for name in before["codecs"]}
    assert older_codecs == set(after["codecs"])  # type: ignore[arg-type]
    assert before["status"] == after["status"] == "OBSERVATION"


def test_the_installer_collector_bundles_the_same_logs_programs_and_facts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = older("installer-diagnostics.py")
    marker = tmp_path / "installer-payload.json"
    marker.write_text(json.dumps({"reference": "localhost/apex-payload:" + "b" * 64}))
    boot = tmp_path / "boot-id"
    boot.write_text("fixture-boot\n")
    calls: list[list[str]] = []
    read: list[str] = []

    def command(argv: list[Any], **_: Any) -> subprocess.CompletedProcess[Any]:
        rendered = [str(item) for item in argv]
        calls.append(rendered)
        if rendered[0] == "systemd-detect-virt":
            return subprocess.CompletedProcess(rendered, 0, "kvm\n", "")
        return subprocess.CompletedProcess(rendered, 0, b"observed\n", b"")

    def read_log(path: Any) -> dict[str, str]:
        read.append(str(path))
        return {"error": "fixture has no logs"}

    def located(value: str) -> Path:
        return marker if value.endswith("installer-payload.json") else boot

    monkeypatch.setattr(module, "Path", located)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module, "read_log", read_log)
    monkeypatch.setattr(module.subprocess, "run", command)
    module.main(TOKEN)
    before = installerlogs.decode(capsys.readouterr().out.encode().splitlines(keepends=True), TOKEN)

    files = installer()
    process = answering(*(tuple(argv) for argv in installer_diagnostics_unit.COMMANDS.values()))
    after = installer_diagnostics_unit.run(bundle(process, files), arguments={})

    assert [list(call) for call in process.calls] == calls
    assert set(before) - {"token"} == set(after)
    assert before["boot_id"] == after["boot_id"] == "fixture-boot"
    assert before["payload"] == after["payload"]
    assert set(before["logs"]) == set(after["logs"])  # type: ignore[arg-type]
    assert list(before["observations"]) == list(after["observations"])  # type: ignore[arg-type]
    assert read == [
        "/run/apex/installer-preflight.json",
        "/tmp/anaconda.log", "/tmp/storage.log", "/tmp/program.log",
    ]
    assert defaults.LOG_LIMIT.value == module.LIMIT

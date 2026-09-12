"""The payload fault mutates the same bytes and judges the same outcomes as the older script.

The older script's directories are patched onto a tree built from the same spec as the
unit's fake tree; each case's mutation must leave the same backup, the same target and the
same digests on both sides, and the same set of outcomes must be the one passing run.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import pathlib
import types
from pathlib import Path
from typing import Any

import pytest
from installerfixtures import (
    ERRORS,
    WRONG_KEY,
    InstallerSpec,
    installer_guest,
    older_tree,
)

from apex.agent import guestguard
from apex.agent.units import installer_payload_unit
from apex.config import defaults
from apex.kernel import safepaths

REPOSITORY = Path(__file__).resolve().parents[2]


def older(base: Path, monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "fault_guest", REPOSITORY / "guest" / "test-installer-fault.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rooted = {
        "PAYLOAD": base / defaults.INSTALLER_PAYLOAD.lstrip("/"),
        "TRUST": base / defaults.INSTALLER_TRUST.lstrip("/"),
        "FAULT_DIRECTORY": base / defaults.INSTALLER_FAULT_DIRECTORY.lstrip("/"),
        "POLICY": base / defaults.CONTAINER_POLICY.lstrip("/"),
        "PREFLIGHT": base / defaults.INSTALLER_PREFLIGHT_RECORD.lstrip("/"),
        "PREFLIGHT_PROGRAM": REPOSITORY / "guest" / "installer-preflight.py",
    }
    for name, value in rooted.items():
        monkeypatch.setattr(module, name, value)
    return module


@pytest.fixture(autouse=True)
def as_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)


def snapshot_older(base: Path) -> dict[str, bytes | None]:
    return {
        "/" + str(path.relative_to(base)): path.read_bytes()
        for path in sorted(base.rglob("*"))
        if path.is_file()
    }


def snapshot_newer(files: Any, names: list[str]) -> dict[str, bytes | None]:
    found: dict[str, bytes | None] = {}
    for name in names:
        path = safepaths.SafePath(Path(name))
        found[name] = files.read_bytes(path, limit=1 << 20) if files.exists(path) else None
    return found


@pytest.mark.parametrize("case", sorted(installer_payload_unit.CASES))
def test_both_sides_leave_the_same_files_after_each_mutation(
    case: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = InstallerSpec()
    base = older_tree(spec, tmp_path / "older")
    module = older(base, monkeypatch)
    key = WRONG_KEY if case == "wrong-key" else ""

    before = module.mutate(case, key)
    older_files = snapshot_older(base)

    _, files, ports = installer_guest(spec, case)
    after = installer_payload_unit.mutate(ports, case, key)
    names = [
        *older_files,
        f"{defaults.INSTALLER_PAYLOAD}/signature-1",
        f"{defaults.INSTALLER_FAULT_DIRECTORY}/original",
    ]
    newer_files = snapshot_newer(files, sorted(set(names)))

    assert after["before_sha256"] == before["before_sha256"]
    assert after["after_sha256"] == before["after_sha256"]
    assert str(after["target"]) == "/" + str(Path(before["target"]).relative_to(base))
    for name, content in older_files.items():
        if name.endswith(".json") and content is not None and newer_files[name] is not None:
            assert json.loads(newer_files[name] or b"") == json.loads(content)  # type: ignore[arg-type]
        else:
            assert newer_files[name] == content, name
    assert newer_files[f"{defaults.INSTALLER_PAYLOAD}/signature-1"] == older_files.get(
        f"{defaults.INSTALLER_PAYLOAD}/signature-1"
    )


OUTCOMES = [
    ("as-expected", {}, "PASS"),
    ("entry-point-succeeded", {"entry_exit": 0}, "FAIL"),
    ("preflight-passed", {"preflight_status": "PASS"}, "FAIL"),
    ("other-complaint", {"preflight_error": "some other complaint"}, "FAIL"),
    ("upstream-log", {"creates_log": True}, "FAIL"),
    ("permissive-after", {"enforcement_after": "Permissive"}, "FAIL"),
]


@pytest.mark.parametrize("name,changes,expected", OUTCOMES)
def test_both_sides_judge_the_entry_point_s_outcome_the_same_way(
    name: str,
    changes: dict[str, object],
    expected: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    spec = InstallerSpec(**changes)  # type: ignore[arg-type]
    base = older_tree(spec, tmp_path / "older")
    module = older(base, monkeypatch)
    log = base / "tmp" / "anaconda.log"
    error = spec.preflight_error
    if error is None:
        error = ERRORS["missing-signature"]

    def run(argv: list[Any], **_: Any) -> types.SimpleNamespace:
        module.PREFLIGHT.parent.mkdir(parents=True, exist_ok=True)
        module.PREFLIGHT.write_text(json.dumps({"status": spec.preflight_status, "error": error}))
        if spec.creates_log:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("log\n")
        return types.SimpleNamespace(returncode=spec.entry_exit, stdout="", stderr="blocked")

    original_exists = pathlib.Path.exists

    def exists(self: Path) -> bool:
        if str(self) == defaults.ANACONDA_LOG:
            return log.exists()
        return original_exists(self)

    monkeypatch.setattr(module, "guard", lambda case: {})
    monkeypatch.setattr(module, "mutate", lambda case, key: {})
    monkeypatch.setattr(module, "run", lambda argv: spec.enforcement_after)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(pathlib.Path, "exists", exists)
    with contextlib.suppress(RuntimeError):
        module.main("missing-signature")  # It raises after printing; the report is the parity.
    printed = capsys.readouterr().out
    before = json.loads(printed.split("APEXFAULT:", 1)[1])

    _, _, ports = installer_guest(spec, "missing-signature")
    after = installer_payload_unit.run(ports, arguments={"case": "missing-signature"})

    assert after["status"] == before["status"] == expected, name

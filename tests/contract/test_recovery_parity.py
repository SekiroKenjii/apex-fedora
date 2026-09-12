"""The recovery units read and judge an installed guest the way the older scripts did.

The prerequisites probe is compared on the programs it runs and the files it opens. The
installed probe is compared on its judgement: the same spec builds the older script's tree
on disk and the unit's tree in memory, and each mutation must be accepted or refused by both.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import io
import pathlib
import types
from pathlib import Path
from typing import Any

import pytest
from recoveryfixtures import (
    BOOTED,
    InstalledSpec,
    config_digest,
    installed_guest,
    older_tree,
)

from apex.agent import guestguard
from apex.agent.units import recovery_installed_unit, recovery_prerequisites_unit
from apex.kernel import errors

REPOSITORY = Path(__file__).resolve().parents[2]


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


def test_the_prerequisites_probe_runs_the_same_programs_and_opens_the_same_files(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = older("recovery-probe.py")
    spec = InstalledSpec()
    calls: list[list[str]] = []
    opened: list[str] = []
    original_open = pathlib.Path.open

    def run(argv: list[Any], **_: Any) -> types.SimpleNamespace:
        rendered = [str(item) for item in argv]
        calls.append(rendered)
        return types.SimpleNamespace(
            returncode=0, stdout=spec.outputs.get(tuple(rendered), b"").decode(), stderr=""
        )

    def opening(self: Path, *arguments: Any, **keywords: Any) -> Any:
        if str(self) in spec.files:
            opened.append(str(self))
            return io.BytesIO(spec.files[str(self)])
        return original_open(self, *arguments, **keywords)

    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(pathlib.Path, "open", opening)
    monkeypatch.setattr(pathlib.Path, "exists", lambda self: str(self) in spec.files)
    module.main()
    capsys.readouterr()

    process, ports = installed_guest(spec)
    recovery_prerequisites_unit.run(ports, arguments={})

    assert [list(call) for call in process.calls] == calls
    assert set(opened) == set(recovery_prerequisites_unit.FILES)


def older_accepts(spec: InstalledSpec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> bool:
    module = older("installed-recovery-probe.py")
    base = older_tree(spec, tmp_path / "older")

    def output(argv: list[str], *, text: bool) -> str:
        assert text is True
        return spec.outputs[tuple(argv)].decode()

    monkeypatch.setattr(module, "Path", lambda name: base / str(name).lstrip("/"))
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.subprocess, "check_output", output)
    try:
        result = module.verify(BOOTED, config_digest(InstalledSpec()))
    except ValueError:
        return False
    return result["status"] == "PASS"


def newer_accepts(spec: InstalledSpec) -> bool:
    _, ports = installed_guest(spec)
    try:
        report = recovery_installed_unit.run(
            ports,
            arguments={"expected_digest": BOOTED, "config_sha256": config_digest(InstalledSpec())},
        )
    except errors.Refusal:
        return False
    return report["status"] == "PASS"


MUTATIONS = {
    "as-built": InstalledSpec(),
    "grub-changed": dataclasses.replace(InstalledSpec(), grub_suffix=b"changed\n"),
    "separator-missing": dataclasses.replace(InstalledSpec(), fragment=b"save_env boot_success"),
    "system-preset-changed": dataclasses.replace(
        InstalledSpec(), system_preset=b"GREENBOOT_MAX_BOOT_ATTEMPTS=1\nchanged\n"
    ),
    "image-preset-changed": dataclasses.replace(
        InstalledSpec(), image_preset=b"GREENBOOT_MAX_BOOT_ATTEMPTS=1\nchanged\n"
    ),
    "permissive": dataclasses.replace(InstalledSpec(), enforcement="Permissive"),
    "not-virtual": dataclasses.replace(InstalledSpec(), virtualiser="none"),
    "other-deployment": dataclasses.replace(InstalledSpec(), booted="sha256:" + "d" * 64),
}


@pytest.mark.parametrize("mutation", sorted(MUTATIONS))
def test_both_sides_accept_or_refuse_the_same_installed_guests(
    mutation: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = MUTATIONS[mutation]

    before = older_accepts(spec, tmp_path, monkeypatch)
    after = newer_accepts(spec)

    assert after == before
    assert before == (mutation == "as-built")

"""The lock unit and the older script run the same commands and judge the same outcomes.

The older script opens its files and runs its programs with the standard library, so those
are answered in place: the breakpoint files, the guard bytes, the inventory, the sysfs
read-only flag as the commands move it, and every program. The unit runs on the fixture
tree with a process fake that moves the tree the same way. The argument vectors, which of
them ran restricted, and the statuses must agree for the passing run and for two failures.
"""

from __future__ import annotations

import contextlib
import dataclasses
import importlib.util
import json
import pathlib
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from livefixture_trees import GUARD_TEXT
from lockfixtures import CAPS_WITH_ADMIN, CAPS_WITHOUT_ADMIN, DENIAL, DIGEST, breakpoint_guest

from apex.adapters.fakes import fake_process
from apex.agent import guestguard
from apex.agent.units import live_lock_unit
from apex.config import defaults

REPOSITORY = Path(__file__).resolve().parents[2]
RO = "/sys/class/block/vda/ro"


def older_devices() -> list[dict[str, Any]]:
    return [
        {"name": "vda", "dev": "253:0", "rdev": 253 * 256, "ro": "1", "sectors": 4 * 2**21,
         "serial": "apex-other-1", "partition": None, "parent": "block", "holders": [],
         "virtio": True},
    ]


def load_older(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    def load(name: str, filename: str) -> types.ModuleType:
        spec = importlib.util.spec_from_file_location(name, REPOSITORY / "guest" / filename)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    monkeypatch.setitem(
        sys.modules, "apex_live_write", load("apex_live_write", "live-write-denial.py")
    )
    return load("lock_probe", "live-lock-fault.py")


@dataclasses.dataclass
class OlderGuest:
    """Answers the older script's reads and runs, moving its read-only flag and latch."""

    caps: bytes
    restores: bool
    read_only: str = "1"
    latched: bool = False
    calls: list[tuple[list[str], bool]] = dataclasses.field(default_factory=list)

    def read_text(self, original: Any, path: Path, *arguments: Any, **keywords: Any) -> str:
        if str(path) == defaults.MOUNTS:
            return "rootfs / rootfs rw 0 0\n"
        if str(path) == RO:
            return self.read_only + "\n"
        return str(original(path, *arguments, **keywords))

    def is_file(self, original: Any, path: Path) -> bool:
        if str(path) == defaults.INITRD_RELEASE:
            return True
        if str(path) == defaults.PROTECTION_LATCH:
            return self.latched
        return bool(original(path))

    def exists(self, original: Any, path: Path) -> bool:
        if str(path) == defaults.PROTECTION_LATCH:
            return self.latched
        return bool(original(path))

    def run(self, argv: list[str], **keywords: Any) -> types.SimpleNamespace:
        self.calls.append((list(argv), keywords.get("preexec_fn") is not None))
        if argv[:2] == ["blockdev", "--setrw"]:
            self.read_only = "0"
        elif argv[:2] == ["blockdev", "--setro"]:
            self.read_only = "1" if self.restores else "0"
        elif argv[:2] == ["/bin/sh", "-c"]:
            self.latched = True
            return types.SimpleNamespace(
                returncode=1, stdout=self.caps.decode(), stderr=DENIAL.decode()
            )
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    def install(self, module: types.ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
        for name in ("read_text", "is_file", "exists"):
            monkeypatch.setattr(
                pathlib.Path, name, _wrapped(getattr(self, name), getattr(pathlib.Path, name))
            )
        monkeypatch.setattr(pathlib.Path, "read_bytes", lambda self: GUARD_TEXT)
        monkeypatch.setattr(module, "require_live_vm", lambda: None)
        monkeypatch.setattr(module, "inventory", older_devices)
        monkeypatch.setattr(module.subprocess, "run", self.run)
        monkeypatch.setattr(module, "EXPECTED_GUARD_SHA256", DIGEST, raising=False)


def _wrapped(answer: Any, original: Any) -> Any:
    def method(me: Path, *arguments: Any, **keywords: Any) -> Any:
        return answer(original, me, *arguments, **keywords)

    return method


def older_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    caps: bytes = CAPS_WITHOUT_ADMIN,
    restores: bool = True,
) -> tuple[dict[str, Any], list[tuple[list[str], bool]]]:
    module = load_older(monkeypatch)
    older = OlderGuest(caps=caps, restores=restores)
    older.install(module, monkeypatch)
    with contextlib.suppress(RuntimeError):
        module.main()  # The older script raises after printing; the report is the parity.
    report = json.loads(capsys.readouterr().out)
    return report, older.calls


def newer_run(
    monkeypatch: pytest.MonkeyPatch, *, caps: bytes = CAPS_WITHOUT_ADMIN, restores: bool = True
) -> tuple[dict[str, Any], list[tuple[list[str], bool]]]:
    monkeypatch.setattr(guestguard.os, "geteuid", lambda: 0)
    fixture = breakpoint_guest(caps=caps, restores=restores)
    report = live_lock_unit.run(fixture.ports(), arguments={"guard_sha256": DIGEST})
    process = fixture.process
    assert isinstance(process, fake_process.ScriptedProcess)
    calls = [
        (list(argv), bool(restriction))
        for argv, restriction in zip(process.calls, process.restrictions, strict=True)
        if list(argv) != ["systemd-detect-virt", "--vm"]
    ]
    return dict(report), calls


@pytest.mark.parametrize(
    "caps,restores,expected",
    [
        (CAPS_WITHOUT_ADMIN, True, "PASS"),
        (CAPS_WITH_ADMIN, True, "FAIL"),
        (CAPS_WITHOUT_ADMIN, False, "FAIL"),
    ],
)
def test_both_sides_run_the_same_commands_and_reach_the_same_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caps: bytes,
    restores: bool,
    expected: str,
) -> None:
    before, older_calls = older_run(monkeypatch, capsys, caps=caps, restores=restores)
    after, newer_calls = newer_run(monkeypatch, caps=caps, restores=restores)

    assert newer_calls == older_calls
    assert after["status"] == before["status"] == expected
    assert after["kernel_denial"] == before.get("kernel_denial", "FAIL")
    assert after["ro_after_cleanup"] == before["ro_after_cleanup"]
    assert after["failure_latched"] == before["failure_latched"]
    assert [item["restricted_child"] for item in after["commands"]] == [
        item["restricted_child"] for item in before["commands"]
    ]

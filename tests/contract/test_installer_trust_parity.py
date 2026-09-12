"""The trust unit and the older script run the same engine commands and reach the same cases.

Both run from a directory under `/var/tmp` named for the run. Every program is answered the
same way on both sides, every key or copy leaves the same files, the proxy check is stood in
for by one stub, and the older script records its commands itself while the unit's are
recorded by the engine's process port. The argument vectors must agree once the run
directories and identifiers are normalised, and both reports must name the same cases.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import secrets
import shutil
import types
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import fake_blockdevices, fake_clock, fake_extents, fake_ids, fake_process
from apex.adapters.real import real_archives, real_containers, real_digesting, real_files
from apex.agent import agentports, builder
from apex.agent.units import installer_trust_unit
from apex.config import defaults
from apex.trust import preflight

REPOSITORY = Path(__file__).resolve().parents[2]
VAR_TMP = Path("/var/tmp")
HEX_32 = re.compile(r"[0-9a-f]{32}")
REJECTING = {
    "wrong-policy.json", "wrong-identity-policy.json", "unsigned-policy.json",
    "tampered-signature-policy.json", "tampered-manifest-policy.json",
    "unexpected-source-policy.json",
}
MANIFEST = b'{"schemaVersion": 2}'


def rejected(argv: list[str]) -> bool:
    return "--policy" in argv and Path(argv[argv.index("--policy") + 1]).name in REJECTING


def answer(argv: list[str]) -> tuple[int, str, str]:
    """What the builder says to each program, and what it leaves on disk."""
    if argv[0] == "systemd-detect-virt":
        return 0, "kvm\n", ""
    if argv == ["skopeo", "--version"]:
        return 0, "skopeo version 1.20\n", ""
    if argv[:2] == ["podman", "info"]:
        return 0, "overlay /var/lib/containers/storage\n", ""
    if argv[:2] == ["skopeo", "generate-sigstore-key"]:
        prefix = Path(argv[argv.index("--output-prefix") + 1])
        prefix.with_suffix(".pub").write_bytes(b"public key " + prefix.name.encode())
        prefix.with_suffix(".private").write_bytes(b"private key")
        return 0, "", ""
    if argv[0] == "skopeo" and "copy" in argv:
        if rejected(argv):
            return 1, "", "FATAL: signature rejected by policy\n"
        if argv[-1].startswith("dir:"):
            destination = Path(argv[-1].removeprefix("dir:"))
            destination.mkdir(parents=True, exist_ok=True)
            (destination / "manifest.json").write_bytes(MANIFEST)
            (destination / "signature-1").write_bytes(b"signature bytes")
        return 0, "", ""
    return 0, "", ""


class Proxy:
    def verified_open(self, source: str, policy: Path) -> dict[str, object]:
        if Path(policy).name in REJECTING:
            raise RuntimeError("Signature rejected by policy")
        return {"protocol": "0.2.8", "method": "OpenImage", "source": source}


@pytest.fixture
def workspaces() -> Iterator[tuple[Path, Path]]:
    if not os.access(VAR_TMP, os.W_OK):
        pytest.skip("NOT TESTED: /var/tmp is not writable here")
    older = VAR_TMP / f"apex-trust-{secrets.token_hex(16)}"
    newer = VAR_TMP / f"apex-trust-{secrets.token_hex(16)}"
    older.mkdir(mode=0o700)
    newer.mkdir(mode=0o700)
    umask = os.umask(0o022)
    os.umask(umask)
    try:
        yield older, newer
    finally:
        os.umask(umask)
        shutil.rmtree(older, ignore_errors=True)
        shutil.rmtree(newer, ignore_errors=True)


def older_run(
    work: Path, policy: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[list[str]], dict[str, Any]]:
    spec = importlib.util.spec_from_file_location(
        "trust_script", REPOSITORY / "guest" / "test-installer-trust.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls: list[list[str]] = []
    original_read_text = pathlib.Path.read_text
    original_is_file = pathlib.Path.is_file
    original_read_bytes = pathlib.Path.read_bytes

    def read_text(self: Path, *arguments: Any, **keywords: Any) -> str:
        if str(self) == defaults.BUILDER_MARKER:
            return f"{defaults.BUILDER_MARKER_TEXT}\n"
        return original_read_text(self, *arguments, **keywords)

    def is_file(self: Path) -> bool:
        return str(self) == defaults.BUILDER_MARKER or original_is_file(self)

    def read_bytes(self: Path) -> bytes:
        if str(self) == defaults.CONTAINER_POLICY:
            return policy.read_bytes()
        return original_read_bytes(self)

    def run(argv: list[Any], **_: Any) -> types.SimpleNamespace:
        rendered = [str(item) for item in argv]
        calls.append(rendered)
        code, out, err = answer(rendered)
        return types.SimpleNamespace(returncode=code, stdout=out, stderr=err)

    class Loader:
        def exec_module(self, module: types.ModuleType) -> None:
            module.verified_open = Proxy().verified_open  # type: ignore[attr-defined]

    stub = types.SimpleNamespace(
        spec_from_file_location=lambda *_: types.SimpleNamespace(loader=Loader()),
        module_from_spec=lambda _: types.ModuleType("preflight_stub"),
    )
    monkeypatch.setattr(module.importlib, "util", stub)
    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    monkeypatch.setattr(pathlib.Path, "is_file", is_file)
    monkeypatch.setattr(pathlib.Path, "read_bytes", read_bytes)
    monkeypatch.setattr(module.tempfile, "mkdtemp", lambda **_: str(work))
    module.main()
    return calls, json.loads((work / "output" / "results.json").read_text())


class Answering(fake_process.ScriptedProcess):
    def run(self, argv: Any, **keywords: Any) -> Any:
        code, out, err = answer(list(argv))
        reply = fake_process.Reply(exit_code=code, stdout=out.encode(), stderr=err.encode())
        self.expect(tuple(argv), reply)
        return super().run(argv, **keywords)


def newer_run(
    work: Path, policy: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[list[list[str]], dict[str, Any]]:
    process = Answering()
    marker = tmp_path / "apex-builder"
    marker.write_text(f"{defaults.BUILDER_MARKER_TEXT}\n")
    loaded = preflight.load()
    monkeypatch.setattr(loaded.program, "verified_open", Proxy().verified_open)
    monkeypatch.setattr(preflight, "load", lambda: loaded)
    monkeypatch.setattr(defaults, "BUILDER_MARKER", str(marker))
    monkeypatch.setattr(defaults, "CONTAINER_POLICY", str(policy))
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    ports = agentports.AgentPorts(
        processes=process,
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        containers=real_containers.PodmanEngine(process),
        digests=real_digesting.CachedDigests(),
        archives=real_archives.TarArchives(),
        identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(),
        blocks=fake_blockdevices.FakeBlockDevices(),
    )
    report = installer_trust_unit.run(ports, arguments={"work": str(work)})
    return [list(call) for call in process.calls], dict(report)


def normalised(calls: list[list[str]], work: Path) -> list[list[str]]:
    identifier = work.name.removeprefix("apex-trust-")
    return [
        [item.replace(str(work), "WORK").replace(identifier, "ID") for item in call]
        for call in calls
        if call[0] != "systemd-detect-virt"
    ]


def test_both_sides_run_the_same_commands_and_pass_the_same_cases(
    workspaces: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    older, newer = workspaces
    policy = tmp_path / "policy.json"
    policy.write_bytes(b'{"default": [{"type": "reject"}]}')

    older_calls, before = older_run(older, policy, monkeypatch)
    newer_calls, after = newer_run(newer, policy, tmp_path, monkeypatch)

    assert normalised(newer_calls, newer) == normalised(older_calls, older)
    assert after["cases"] == before["cases"]
    assert after["proxy_cases"] == before["proxy_cases"]
    assert after["status"] == before["status"] == "PASS"
    assert after["manifest_digest"] == before["manifest_digest"]
    assert HEX_32.fullmatch(older.name.removeprefix("apex-trust-"))

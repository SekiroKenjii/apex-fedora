"""The unit and the older script build and sign the fixture with the same commands.

Both run from a directory under `/var/tmp` named for the run, with every program answered
and the files a copy or a key generation would leave written by the answer. The older script
records its commands itself; the unit's are recorded by the engine's process port. The two
sequences must agree once the run directories and identifiers are normalised.
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
from apex.agent.units import update_fixture_unit
from apex.config import defaults
from apex.kernel import hashing, quantities
from apex.provisioning.fixtures import update_fixture

REPOSITORY = Path(__file__).resolve().parents[2]
VAR_TMP = Path("/var/tmp")
RAW = b'{"schemaVersion": 2, "config": {"digest": "sha256:' + b"c" * 64 + b'"}}'
BLOB = b"layer bytes"
GREENBOOT = b"GREENBOOT_MAX_BOOT_ATTEMPTS=1\n"
HEX_32 = re.compile(r"[0-9a-f]{32}")


def populate(work: Path) -> None:
    (work / "guest").mkdir()
    (work / "guest" / "fix-grub-fragment.py").write_text("print('fragment')\n")
    preset = work / "system_files" / "usr" / "share" / "apex"
    preset.mkdir(parents=True)
    (preset / "greenboot.conf").write_bytes(GREENBOOT)
    (work / "target-image.json").write_text(json.dumps({
        "profile": "fedora",
        "digest": str(hashing.digest_bytes(RAW)),
        "image_id": "sha256:" + "c" * 64,
    }))


def answer(argv: list[str]) -> str:
    """What the builder says to each program, and what it leaves on disk."""
    greenboot = hashing.digest_bytes(GREENBOOT).hex
    if argv[0] == "systemd-detect-virt":
        return "kvm\n"
    if argv[:3] == ["skopeo", "inspect", "--raw"]:
        return RAW.decode()
    if argv[:2] == ["skopeo", "generate-sigstore-key"]:
        prefix = Path(argv[argv.index("--output-prefix") + 1])
        prefix.with_suffix(".pub").write_bytes(b"public key " + prefix.name.encode())
        prefix.with_suffix(".private").write_bytes(b"private key")
        return ""
    if argv[0] == "skopeo" and "copy" in argv:
        destination = Path(argv[-1].removeprefix("dir:"))
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "manifest.json").write_bytes(RAW)
        (destination / hashing.digest_bytes(BLOB).hex).write_bytes(BLOB)
        key = argv[argv.index("--sign-by-sigstore-private-key") + 1]
        (destination / "signature-1").write_bytes(b"signed by " + key.encode())
        return ""
    if argv[:2] == ["podman", "run"] and argv[-1] == update_fixture.RPM_QUERY[-1]:
        return "pkg-1\npkg-0\n"
    if argv[:2] == ["podman", "run"] and argv[-2] == "-c":
        return (
            f"{greenboot}  /etc/greenboot/greenboot.conf\n"
            f"{greenboot}  /usr/share/apex/greenboot.conf\n"
            f"{'d' * 64}  {update_fixture.FRAGMENT}\n"
        )
    if argv[0] == "findmnt":
        return "ext4\n"
    return ""


@pytest.fixture
def workspaces() -> Iterator[tuple[Path, Path]]:
    if not os.access(VAR_TMP, os.W_OK):
        pytest.skip("NOT TESTED: /var/tmp is not writable here")
    older = VAR_TMP / f"apex-update-{secrets.token_hex(16)}"
    newer = VAR_TMP / f"apex-update-{secrets.token_hex(16)}"
    for work in (older, newer):
        work.mkdir(mode=0o700)
        populate(work)
    umask = os.umask(0o022)
    os.umask(umask)
    try:
        yield older, newer
    finally:
        os.umask(umask)
        shutil.rmtree(older, ignore_errors=True)
        shutil.rmtree(newer, ignore_errors=True)


def older_calls(work: Path, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    spec = importlib.util.spec_from_file_location(
        "update_fixture_script", REPOSITORY / "guest" / "update-fixture.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls: list[list[str]] = []
    original_read_text = pathlib.Path.read_text
    original_digest = module.digest

    def read_text(self: Path, *arguments: Any, **keywords: Any) -> str:
        if str(self) == defaults.BUILDER_MARKER:
            return f"{defaults.BUILDER_MARKER_TEXT}\n"
        return original_read_text(self, *arguments, **keywords)

    def run(argv: list[Any], **_: Any) -> types.SimpleNamespace:
        rendered = [str(item) for item in argv]
        calls.append(rendered)
        return types.SimpleNamespace(returncode=0, stdout=answer(rendered), stderr="")

    def check_output(argv: list[Any], **_: Any) -> str:
        rendered = [str(item) for item in argv]
        calls.append(rendered)
        return answer(rendered)

    monkeypatch.setattr(module.os, "geteuid", lambda: 0)
    monkeypatch.setattr(module.subprocess, "run", run)
    monkeypatch.setattr(module.subprocess, "check_output", check_output)
    monkeypatch.setattr(pathlib.Path, "read_text", read_text)
    monkeypatch.setattr(
        module.shutil, "disk_usage", lambda _path: types.SimpleNamespace(free=100 * 1024**3)
    )
    def digest(path: Any) -> str:
        return "0" * 64 if str(path) == update_fixture.BUILDER_POLICY else original_digest(path)

    monkeypatch.setattr(module, "digest", digest)
    monkeypatch.chdir(work)
    module.main()
    return calls


class Answering(fake_process.ScriptedProcess):
    def run(self, argv: Any, **keywords: Any) -> Any:
        self.expect(tuple(argv), fake_process.Reply(stdout=answer(list(argv)).encode()))
        return super().run(argv, **keywords)


def newer_calls(work: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    process = Answering()
    marker = tmp_path / "apex-builder"
    marker.write_text(f"{defaults.BUILDER_MARKER_TEXT}\n")
    policy = tmp_path / "policy.json"
    policy.write_bytes(b"{}")
    monkeypatch.setattr(defaults, "BUILDER_MARKER", str(marker))
    monkeypatch.setattr(update_fixture, "BUILDER_POLICY", str(policy))
    monkeypatch.setattr(builder.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        real_files.LocalFiles, "free_space", lambda self, path: quantities.Gib(100).as_bytes()
    )
    ports = agentports.AgentPorts(
        processes=process,
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        containers=real_containers.PodmanEngine(process),
        digests=real_digesting.CachedDigests(),
        archives=real_archives.TarArchives(),
        identities=fake_ids.SequenceIdentities(),
        extents=fake_extents.FakeExtents(), blocks=fake_blockdevices.FakeBlockDevices(),
    )
    update_fixture_unit.run(ports, arguments={"work": str(work)})
    return [list(call) for call in process.calls]


def normalised(calls: list[list[str]], work: Path) -> list[list[str]]:
    return [
        [HEX_32.sub("<id>", item.replace(str(work), "<work>")) for item in argv] for argv in calls
    ]


def test_the_unit_and_the_older_script_run_the_same_commands(
    workspaces: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    older_work, newer_work = workspaces

    older = normalised(older_calls(older_work, monkeypatch), older_work)
    monkeypatch.undo()
    newer = normalised(newer_calls(newer_work, tmp_path, monkeypatch), newer_work)

    assert newer == older


def test_both_leave_the_same_bundle_layout(
    workspaces: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    older_work, newer_work = workspaces
    older_calls(older_work, monkeypatch)
    monkeypatch.undo()
    newer_calls(newer_work, tmp_path, monkeypatch)

    def layout(work: Path) -> set[str]:
        bundle = work / "bundle"
        return {str(path.relative_to(bundle)) for path in bundle.rglob("*") if path.is_file()}

    assert layout(newer_work) == layout(older_work)
    assert (newer_work / "output" / "payloads.tar").is_file()
    report = json.loads((newer_work / "output" / "results.json").read_text())
    assert report["status"] == "PASS"
    assert set(report["images"]) == {"a", "b"}

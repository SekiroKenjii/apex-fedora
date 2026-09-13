"""The recipes issue, word for word and in order, the host commands the older build issues.

The older `_execute` is run with its effects captured: the shell it opens, the copies it
makes and the build it starts are recorded instead of performed. The recipe runs on the real
guest shell adapter over a recording process port. For every artifact kind the two argument
vector sequences must agree once run identifiers are normalised.
"""

from __future__ import annotations

import json
import re
import types
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from apex.adapters.fakes import (
    fake_clock,
    fake_downloading,
    fake_hypervisor,
    fake_ids,
    fake_locking,
    fake_qmp,
    fake_signing,
)
from apex.adapters.real import real_archives, real_digesting, real_files, real_guestshell
from apex.composition import buildplan
from apex.composition.recipes import disk_artifact_recipe, image_recipe, live_artifact_recipe
from apex.config import defaults
from apex.kernel import claims, commands, hashing, identifiers, safepaths, timing
from apex.model import builds
from apex.ports import guestshell, portset, process
from apexlib import pipeline as legacy

REPOSITORY = Path(__file__).resolve().parents[2]
PARENT = identifiers.BuildId("b" * 32)
IMAGE_ID = "c" * 64
HEX_32 = re.compile(r"[0-9a-f]{32}")


class RecordingProcess(process.ProcessPort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(
        self,
        argv: commands.Argv,
        *,
        deadline: timing.Deadline,  # noqa: ARG002
        limit: commands.OutputLimit,  # noqa: ARG002
        stdin: bytes | None = None,  # noqa: ARG002
        transcript: safepaths.SafePath | None = None,  # noqa: ARG002
        cwd: safepaths.SafePath | None = None,  # noqa: ARG002
        variables: Mapping[str, str] | None = None,  # noqa: ARG002
        dropping: frozenset[commands.Capability] = frozenset(),  # noqa: ARG002
    ) -> commands.CompletedRun:
        self.calls.append(list(argv))
        return commands.CompletedRun(exit_code=0, stdout=b"", stderr=b"", truncated=False)

    def locate(self, program: str) -> Path | None:  # noqa: ARG002
        return None


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / defaults.BUILDER_KEY_NAME).write_bytes(b"")
    return safepaths.RuntimeRoot.adopt(base)


def parent_documents(root: safepaths.RuntimeRoot) -> None:
    export = root.path / "exports" / str(PARENT)
    (export / "output").mkdir(parents=True)
    manifest = json.dumps({"config": {"digest": f"sha256:{IMAGE_ID}"}}).encode()
    (export / "output" / "manifest.json").write_bytes(manifest)
    (export / "output" / "image.json").write_text(json.dumps({
        "profile": "fedora", "digest": str(hashing.digest_bytes(manifest)),
        "image_id": f"sha256:{IMAGE_ID}",
    }))
    (export / "result.json").write_text(json.dumps({
        "status": "PASS", "kind": "image", "profile": "fedora", "source_sha256": "a" * 64,
        "remote": f"/var/tmp/apex-{PARENT}", "parent_build": None, "test_access": False,
    }))


def older_calls(
    root: safepaths.RuntimeRoot, monkeypatch: pytest.MonkeyPatch, kind: str, parent: str | None
) -> list[list[str]]:
    calls: list[list[str]] = []
    directory = root.path
    connection = [
        "ssh", "-i", str(directory / "builder_ed25519"), "-p", "22244",
        "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={directory}/known_hosts",
        "builder@127.0.0.1",
    ]

    def record(arguments: list[Any], **_: Any) -> types.SimpleNamespace:
        calls.append([str(item) for item in arguments])
        return types.SimpleNamespace(returncode=0, stdout=iter(()), wait=lambda: 0)

    monkeypatch.setattr(legacy, "ssh_args", lambda _directory: list(connection))
    monkeypatch.setattr(legacy, "acquire", lambda _directory: {})
    monkeypatch.setattr(legacy, "run", record)
    monkeypatch.setattr(legacy.subprocess, "Popen", record)
    monkeypatch.setattr(legacy.subprocess, "run", record)
    legacy._execute(directory, "fedora", kind, parent, False)  # noqa: SLF001
    return calls


def newer_calls(root: safepaths.RuntimeRoot, kind: builds.ArtifactKind) -> list[list[str]]:
    recorder = RecordingProcess()
    ports = portset.HostPorts(
        processes=recorder,
        files=real_files.LocalFiles(),
        clock=fake_clock.ManualClock(),
        identities=fake_ids.SequenceIdentities(),
        locks=fake_locking.MemoryLocks(),
        digests=real_digesting.CachedDigests(),
        archives=real_archives.TarArchives(),
        signing=fake_signing.FakeSigner(),
        downloads=fake_downloading.PinningFetcher(),
        hypervisor=fake_hypervisor.FakeQemu(),
        monitor=fake_qmp.ScriptedQmp(),
        guest=real_guestshell.OpensshGuestShell(recorder),
    )
    target = guestshell.GuestTarget(
        user=defaults.BUILDER_USER,
        port=defaults.BUILDER_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / defaults.BUILDER_KEY_NAME, within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )
    plan = {
        builds.ArtifactKind.IMAGE: image_recipe.PLAN,
        builds.ArtifactKind.LIVE: live_artifact_recipe.PLAN,
    }.get(kind, disk_artifact_recipe.PLAN)
    outcome = buildplan.run(
        plan, ports, repository=safepaths.SourceRoot.adopt(REPOSITORY), runtime_root=root,
        builder=target, profile=builds.Profile.FEDORA, kind=kind,
        parent=None if kind is builds.ArtifactKind.IMAGE else PARENT,
    )
    assert outcome.succeeded, outcome.detail
    return recorder.calls


def normalised(calls: list[list[str]]) -> list[list[str]]:
    return [[HEX_32.sub("<id>", item) for item in call] for call in calls]


# The older NVIDIA build was its own host path, one scp carrying two files; the recipe reuses
# the shared transfer, and its guest command line is asserted by the pipeline test instead.
SHARED_KINDS = [kind for kind in builds.ArtifactKind if kind is not builds.ArtifactKind.NVIDIA]


@pytest.mark.parametrize("kind", SHARED_KINDS)
def test_the_recipe_and_the_older_build_issue_the_same_host_commands(
    root: safepaths.RuntimeRoot, monkeypatch: pytest.MonkeyPatch, kind: builds.ArtifactKind
) -> None:
    parent = None if kind is builds.ArtifactKind.IMAGE else str(PARENT)
    if parent is not None:
        parent_documents(root)

    older = normalised(older_calls(root, monkeypatch, str(kind), parent))
    newer = normalised(newer_calls(root, kind))

    assert newer == older

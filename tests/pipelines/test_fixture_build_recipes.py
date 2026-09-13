"""The update fixtures and the recovery disk on fakes: made in the builder, brought home checked."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import posixpath
from pathlib import Path
from typing import Any

import parentbuild
import pytest
from answeringguest import AnsweringGuest
from mirroredfiles import MirroredFiles

from apex.adapters.fakes import fake_downloading
from apex.adapters.real import real_digesting
from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import refusals, safepaths
from apex.ports import guestshell, portset
from apex.verification import updatefixtures, verifykeys
from apex.verification.recipes import recovery_disk_recipe, update_fixtures_recipe

REPOSITORY = safepaths.SourceRoot.adopt(Path(__file__).resolve().parents[2])
PRIVATE = defaults.RECORD_MODE
FIXTURE = "c" * 32
PAYLOADS = b"tar of payloads"
PUBLIC_KEY = b"-----BEGIN PUBLIC KEY-----\nfixture\n-----END PUBLIC KEY-----\n"
MANIFEST_A = b'{"config": {"digest": "sha256:' + b"1" * 64 + b'"}}'
MANIFEST_B = b'{"config": {"digest": "sha256:' + b"2" * 64 + b'"}}'


def fixture_report() -> dict[str, Any]:
    return {
        "status": "PASS", "id": FIXTURE,
        "images": {
            "a": {
                "digest": "sha256:" + hashlib.sha256(MANIFEST_A).hexdigest(),
                "config": "sha256:" + "1" * 64, "identity": f"localhost/apex-recovery-{FIXTURE}:a",
            },
            "b": {
                "digest": "sha256:" + hashlib.sha256(MANIFEST_B).hexdigest(),
                "config": "sha256:" + "2" * 64, "identity": f"localhost/apex-recovery-{FIXTURE}:b",
            },
        },
        "files": {"a/manifest.json": hashlib.sha256(MANIFEST_A).hexdigest()},
        "public_key_sha256": hashlib.sha256(PUBLIC_KEY).hexdigest(),
        "archive_sha256": hashlib.sha256(PAYLOADS).hexdigest(),
        "greenboot_config_sha256": "9" * 64,
    }


class DeliveringGuest(AnsweringGuest):
    """A guest whose retrieved output lands on the disk and in the file port."""

    def __init__(
        self, filesystem: MirroredFiles, answers: dict[str, Any], outputs: dict[str, bytes]
    ) -> None:
        super().__init__(answers)
        self.filesystem = filesystem
        self.outputs = outputs

    def receive(
        self, target: Any, *, remote: Any, into: Any, recursive: bool, deadline: Any
    ) -> None:
        super().receive(target, remote=remote, into=into, recursive=recursive, deadline=deadline)
        home = into.path / posixpath.basename(str(remote))
        for name, data in self.outputs.items():
            self.filesystem.write_atomic(safepaths.SafePath(home / name), data, mode=PRIVATE)


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    (base / "builder_ed25519").write_bytes(b"")
    (base / "apex-agent.whl").write_bytes(b"not a wheel")
    return safepaths.RuntimeRoot.adopt(base)


def builder(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user=defaults.BUILDER_USER, port=defaults.BUILDER_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "builder_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def wheel(root: safepaths.RuntimeRoot) -> safepaths.SafePath:
    return safepaths.SafePath.regular_file(root.path / "apex-agent.whl", within=root)


def held(
    ports: portset.HostPorts, files: MirroredFiles, guest: DeliveringGuest
) -> portset.HostPorts:
    return dataclasses.replace(
        ports, files=files, guest=guest, downloads=fake_downloading.PinningFetcher(),
        digests=real_digesting.CachedDigests(),
    )


def test_the_update_fixtures_are_made_by_the_agent_over_the_imported_payload(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    parentbuild.documents(files, root)
    guest = DeliveringGuest(
        files,
        {"build.import-payload": {"tag": "x"}, "fixture.update": fixture_report()},
        {"results.json": json.dumps(fixture_report()).encode(), "payloads.tar": PAYLOADS,
         "trusted.pub": PUBLIC_KEY},
    )

    outcome = update_fixtures_recipe.build(
        held(ports, files, guest), builder=builder(root), wheel=wheel(root),
        parent=parentbuild.PARENT, root=root, repository=REPOSITORY,
    )

    assert outcome.succeeded, outcome.detail
    run = outcome.facts[composition_keys.RUN_ID]
    work = f"/var/tmp/apex-update-{run}"
    assert guest.asked == ["build.import-payload", "fixture.update"]
    assert guest.requests[0]["arguments"] == {"work": work, "parent": str(parentbuild.PARENT)}
    assert guest.requests[1]["arguments"] == {"work": work}
    sent = [str(item.remote) for item in guest.sent]
    assert f"{work}/target-image.json" in sent
    assert f"{work}/guest/fix-grub-fragment.py" in sent
    assert f"{work}/system_files/usr/share/apex/greenboot.conf" in sent
    home = outcome.facts[verifykeys.FIXTURES]
    assert home.path == root.path / "exports" / str(run) / "output"
    assert (home.path / "payloads.tar").read_bytes() == PAYLOADS
    kept = outcome.facts[verifykeys.retained_observation(update_fixtures_recipe.CASE)]
    assert kept.path.name == "fixture.update.json"


def test_an_archive_that_lost_bytes_fails_the_fixture_run(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    parentbuild.documents(files, root)
    guest = DeliveringGuest(
        files,
        {"build.import-payload": {"tag": "x"}, "fixture.update": fixture_report()},
        {"results.json": b"{}", "payloads.tar": b"truncated", "trusted.pub": PUBLIC_KEY},
    )

    outcome = update_fixtures_recipe.build(
        held(ports, files, guest), builder=builder(root), wheel=wheel(root),
        parent=parentbuild.PARENT, root=root, repository=REPOSITORY,
    )

    assert outcome.refusal is refusals.RefusalReason.STAGE_FAILED
    assert "payloads.tar: checksum mismatch" in outcome.detail


def exported_fixture(
    ports: portset.HostPorts, files: MirroredFiles, root: safepaths.RuntimeRoot
) -> updatefixtures.Located:
    home = root.child(f"exports/{FIXTURE}/output")
    files.write_atomic(home / "results.json", json.dumps(fixture_report()).encode(), mode=PRIVATE)
    files.write_atomic(home / "manifest-a.json", MANIFEST_A, mode=PRIVATE)
    files.write_atomic(home / "manifest-b.json", MANIFEST_B, mode=PRIVATE)
    return updatefixtures.locate(dataclasses.replace(ports, files=files), root, FIXTURE)


def test_the_recovery_disk_is_built_from_image_a_with_the_agent_standing_it_in(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apex.composition import accessgrant  # noqa: PLC0415

    files = MirroredFiles()
    located = exported_fixture(ports, files, root)
    guest = DeliveringGuest(files, {"build.tag-payload": {"tag": "x"}}, {"disk.qcow2": b"disk"})
    monkeypatch.setattr(
        accessgrant, "grant",
        lambda _ports, *, root, run: accessgrant.Granted(
            directory=root.child(f"exports/{run}/test-access"),
            credentials=root.child(f"exports/{run}/test-access/credentials.json"),
            key=root.child(f"exports/{run}/test-access/id_ed25519"),
            blueprint=root.child(f"exports/{run}/test-access/blueprint.toml"),
        ),
    )

    outcome = recovery_disk_recipe.build(
        held(ports, files, guest), repository=REPOSITORY, runtime_root=root,
        builder=builder(root), wheel=wheel(root), fixture=located,
    )

    assert outcome.succeeded, outcome.detail
    run = outcome.facts[composition_keys.RUN_ID]
    remote = f"/var/tmp/apex-{run}"
    assert guest.asked == ["build.tag-payload"]
    assert guest.requests[0]["arguments"] == {
        "work": remote, "source": f"localhost/apex-recovery-{FIXTURE}:a",
        "digest": fixture_report()["images"]["a"]["digest"],
    }
    scripts = [item.script.rendered() for item in guest.runs]
    assert any(
        script == f"cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock "
        "bash -c 'bash guest/disk-artifact.sh qcow2 sha256:" + "1" * 64
        + " && python3 guest/sign-artifacts.py output target-image.json'"
        for script in scripts
    )
    assert any(str(item.remote).endswith("test-blueprint.toml") for item in guest.sent)
    record = outcome.facts[composition_keys.BUILD_RECORD]
    assert str(record.kind) == "qcow2" and record.test_access is True and record.parent is None
    target = json.loads(
        files.read_bytes(exports.inside(root, run, "target-image.json"), limit=4096)
    )
    assert target["fixture"] == FIXTURE and target["ready_to_install"] is False
    disk = json.loads(files.read_bytes(exports.inside(root, run, "fixture-disk.json"), limit=4096))
    assert disk["parent_fixture"] == FIXTURE and "NOT TESTED" in disk["scope"]


def test_a_fixture_whose_manifest_changed_is_refused_before_the_builder_is_touched(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    located = exported_fixture(ports, files, root)
    (root.path / "exports" / FIXTURE / "output" / "manifest-a.json").write_bytes(b"{}")
    guest = DeliveringGuest(files, {}, {})

    outcome = recovery_disk_recipe.build(
        held(ports, files, guest), repository=REPOSITORY, runtime_root=root,
        builder=builder(root), wheel=wheel(root), fixture=located,
    )

    assert outcome.refusal is refusals.RefusalReason.FIXTURE_REPORT_MALFORMED
    assert guest.asked == [] and not any("disk-artifact" in r.script.rendered() for r in guest.runs)

"""The two fingerprint builds on fakes: packages bound to the lock, an image bound to its tests."""

from __future__ import annotations

import dataclasses
import json
import posixpath
from pathlib import Path
from typing import Any

import fingerprintbuilds
import parentbuild
import pytest
from answeringguest import AnsweringGuest
from mirroredfiles import MirroredFiles

from apex.adapters.fakes import fake_downloading, fake_signing
from apex.adapters.real import real_digesting
from apex.composition import exports, keys
from apex.composition.recipes import fingerprint_image_recipe, fingerprint_rpms_recipe
from apex.config import defaults
from apex.kernel import hashing, refusals, safepaths
from apex.model import bundles
from apex.ports import guestshell, portset

REPOSITORY = safepaths.SourceRoot.adopt(Path(__file__).resolve().parents[2])
PRIVATE = defaults.RECORD_MODE


class DeliveringGuest(AnsweringGuest):
    """A guest whose retrieved output lands on the disk and in the file port."""

    def __init__(self, filesystem: MirroredFiles, outputs: dict[str, bytes]) -> None:
        super().__init__({})
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
    return safepaths.RuntimeRoot.adopt(base)


def builder(root: safepaths.RuntimeRoot) -> guestshell.GuestTarget:
    return guestshell.GuestTarget(
        user=defaults.BUILDER_USER,
        port=defaults.BUILDER_SSH_PORT,
        key=safepaths.SafePath.regular_file(root.path / "builder_ed25519", within=root),
        known_hosts=root.child(defaults.KNOWN_HOSTS_NAME),
    )


def held(
    ports: portset.HostPorts, files: MirroredFiles, guest: DeliveringGuest
) -> portset.HostPorts:
    return dataclasses.replace(
        ports,
        files=files,
        guest=guest,
        downloads=fake_downloading.PinningFetcher(),
        digests=real_digesting.CachedDigests(),
    )


def rpm_outputs(root: safepaths.RuntimeRoot) -> dict[str, bytes]:
    """What a package build leaves in its output, from the fixture's report."""
    scratch = MirroredFiles()
    fingerprintbuilds.rpm_build(scratch, root, build=fingerprintbuilds.RPM_BUILD)
    home = root.path / "exports" / str(fingerprintbuilds.RPM_BUILD) / "output"
    return {
        str(path.relative_to(home)): path.read_bytes() for path in home.rglob("*") if path.is_file()
    }


def test_the_packages_are_built_from_the_sources_alone_and_the_report_is_bound(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    guest = DeliveringGuest(files, rpm_outputs(root))

    outcome = fingerprint_rpms_recipe.build(
        held(ports, files, guest), repository=REPOSITORY, runtime_root=root, builder=builder(root)
    )

    assert outcome.succeeded, outcome.detail
    run = outcome.facts[keys.RUN_ID]
    remote = f"/var/tmp/apex-{run}"
    assert [item.script.rendered() for item in guest.runs][2] == (
        f"cd {remote} && tar -xf source.tar && sudo flock -n /run/apex-build.lock bash -c "
        "'bash guest/bootstrap.sh && python3 guest/fingerprint-rpms.py'"
    )
    assert [str(item.remote) for item in guest.sent] == [f"{remote}/source.tar"]
    record = outcome.facts[keys.BUILD_RECORD]
    assert str(record.kind) == "fingerprint-rpms" and str(record.status) == "PASS"
    assert record.parent is None
    verification = json.loads(
        files.read_bytes(
            exports.inside(root, run, defaults.FINGERPRINT_VERIFICATION_NAME), limit=4096
        )
    )
    assert verification["status"] == "PASS" and verification["artifacts"] > 5


def test_a_package_report_the_host_cannot_bind_leaves_a_failed_record(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    outputs = rpm_outputs(root)
    report = json.loads(outputs["results.json"])
    report["hardware"] = "PASS"
    outputs["results.json"] = json.dumps(report).encode()
    guest = DeliveringGuest(files, outputs)

    outcome = fingerprint_rpms_recipe.build(
        held(ports, files, guest), repository=REPOSITORY, runtime_root=root, builder=builder(root)
    )

    assert not outcome.succeeded and "claims a test" in outcome.detail
    run = outcome.facts[keys.RUN_ID]
    record = json.loads(files.read_bytes(exports.inside(root, run, "result.json"), limit=4096))
    assert record["status"] == "FAIL" and record["kind"] == "fingerprint-rpms"


def signed_parent(
    ports: portset.HostPorts, files: MirroredFiles, root: safepaths.RuntimeRoot
) -> None:
    """The parent build's three documents, signed by a development key the root keeps."""
    digest = parentbuild.documents(files, root)
    (root.path / "trust").mkdir(mode=0o700)
    ports.signing.generate_key_pair(
        private_into=root.child("keys/dev.key"), public_into=root.child("trust/development.pub")
    )
    files.adopt(root.child("trust/development.pub"))
    home = root.path / "exports" / str(parentbuild.PARENT) / "output"
    listed = {
        name: hashing.digest_bytes((home / name).read_bytes()).hex
        for name in ("image.json", "manifest.json")
    }
    inventory = json.dumps({"schema": 1, "digest": str(digest), "files": listed}).encode()
    files.write_atomic(safepaths.SafePath(home / bundles.MANIFEST_NAME), inventory, mode=PRIVATE)
    files.write_atomic(
        safepaths.SafePath(home / bundles.SIGNATURE_NAME),
        ports.signing.sign(
            payload=inventory, private_key=safepaths.RegularFile.adopt(root.path / "keys/dev.key")
        ),
        mode=PRIVATE,
    )


def image_outputs(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> dict[str, bytes]:
    """A derived image's signed output: its image document, manifest and inventory."""
    manifest = json.dumps({"config": {"digest": "sha256:" + "f" * 64}}).encode()
    digest = hashing.digest_bytes(manifest)
    image = json.dumps(
        {"profile": "fedora", "digest": str(digest), "image_id": "sha256:" + "f" * 64}
    ).encode()
    listed = {"image.json": hashing.digest_bytes(image).hex, "manifest.json": digest.hex}
    inventory = json.dumps({"schema": 1, "digest": str(digest), "files": listed}).encode()
    signature = ports.signing.sign(
        payload=inventory, private_key=safepaths.RegularFile.adopt(root.path / "keys/dev.key")
    )
    return {
        "image.json": image,
        "manifest.json": manifest,
        bundles.MANIFEST_NAME: inventory,
        bundles.SIGNATURE_NAME: signature,
    }


def test_the_image_binds_the_tested_packages_and_verifies_its_own_signed_output(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    signed_parent(ports, files, root)
    fingerprintbuilds.rpm_build(files, root)
    fingerprintbuilds.gtk_test(files, root)
    guest = DeliveringGuest(files, image_outputs(ports, root))

    outcome = fingerprint_image_recipe.build(
        held(ports, files, guest),
        repository=REPOSITORY,
        runtime_root=root,
        builder=builder(root),
        parent=parentbuild.PARENT,
        rpm_build=fingerprintbuilds.RPM_BUILD,
        gtk_test=fingerprintbuilds.GTK_TEST,
    )

    assert outcome.succeeded, outcome.detail
    run = outcome.facts[keys.RUN_ID]
    remote = f"/var/tmp/apex-{run}"
    sent = [str(item.remote) for item in guest.sent]
    assert sent[:2] == [f"{remote}/source.tar", f"{remote}/target-image.json"]
    assert f"{remote}/fingerprint-request.json" in sent
    assert sum(name.startswith(f"{remote}/inputs/") for name in sent) == 3
    scripts = [run.script.rendered() for run in guest.runs]
    build = [script for script in scripts if "fingerprint-image.py" in script]
    assert len(build) == 1 and "import-payload.sh" in build[0] and "sign-artifacts" not in build[0]
    request = json.loads(
        files.read_bytes(exports.inside(root, run, defaults.FINGERPRINT_REQUEST_NAME), limit=4096)
    )
    assert request["rpm_build"] == str(fingerprintbuilds.RPM_BUILD) and len(request["rpms"]) == 3
    record = outcome.facts[keys.BUILD_RECORD]
    assert str(record.kind) == "fingerprint-image" and str(record.status) == "PASS"
    verified = outcome.facts[keys.FINGERPRINT_REPORT]
    assert verified is not None and verified["files_verified"] == 2


def test_a_dialog_test_of_another_patch_is_refused_before_anything_is_sent(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    signed_parent(ports, files, root)
    fingerprintbuilds.rpm_build(files, root)
    report = fingerprintbuilds.gtk_test(files, root)
    report["patch_sha256"] = "0" * 64
    files.write_atomic(
        exports.inside(root, fingerprintbuilds.GTK_TEST, "output/results.json"),
        json.dumps(report).encode(),
        mode=PRIVATE,
    )
    guest = DeliveringGuest(files, {})

    outcome = fingerprint_image_recipe.build(
        held(ports, files, guest),
        repository=REPOSITORY,
        runtime_root=root,
        builder=builder(root),
        parent=parentbuild.PARENT,
        rpm_build=fingerprintbuilds.RPM_BUILD,
        gtk_test=fingerprintbuilds.GTK_TEST,
    )

    assert outcome.refusal is refusals.RefusalReason.FINGERPRINT_INPUT_MISMATCH
    assert guest.sent == []


def test_an_unsigned_parent_is_refused_and_a_bad_output_signature_fails_the_record(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot
) -> None:
    files = MirroredFiles()
    signed_parent(ports, files, root)
    fingerprintbuilds.rpm_build(files, root)
    fingerprintbuilds.gtk_test(files, root)
    outputs = image_outputs(ports, root)
    outputs[bundles.SIGNATURE_NAME] = b"forged"
    guest = DeliveringGuest(files, outputs)
    rejecting = dataclasses.replace(held(ports, files, guest), signing=fake_signing.FakeSigner())

    outcome = fingerprint_image_recipe.build(
        rejecting,
        repository=REPOSITORY,
        runtime_root=root,
        builder=builder(root),
        parent=parentbuild.PARENT,
        rpm_build=fingerprintbuilds.RPM_BUILD,
        gtk_test=fingerprintbuilds.GTK_TEST,
    )

    assert not outcome.succeeded and "did not verify" in outcome.detail
    run = outcome.facts[keys.RUN_ID]
    record = json.loads(files.read_bytes(exports.inside(root, run, "result.json"), limit=4096))
    assert record["status"] == "FAIL"

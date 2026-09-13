"""A parent build is accepted only when its three documents agree."""

from __future__ import annotations

import json

import pytest

from apex.kernel import errors, hashing, identifiers, refusals, safepaths
from apex.model import builds, oci

CONFIG = "c" * 64


def manifest() -> bytes:
    return json.dumps({"config": {"digest": f"sha256:{CONFIG}"}}).encode()


def frozen(*, digest: str | None = None, image_id: str = CONFIG) -> oci.FrozenImage:
    return oci.FrozenImage(
        profile="fedora",
        digest=identifiers.Digest(digest or hashing.digest_bytes(manifest()).hex),
        image_id=identifiers.ImageId(image_id),
    )


def record(
    status: builds.BuildStatus = builds.BuildStatus.PASS,
    kind: builds.ArtifactKind = builds.ArtifactKind.IMAGE,
) -> builds.BuildRecord:
    return builds.BuildRecord(
        status=status,
        kind=kind,
        profile=builds.Profile.FEDORA,
        source=identifiers.Digest("a" * 64),
        remote=safepaths.RemotePath("/var/tmp/apex-run"),
        parent=None,
        test_access=False,
    )


def test_a_completed_image_whose_documents_agree_is_frozen() -> None:
    assert builds.require_frozen(record(), frozen(), manifest()) == frozen()


@pytest.mark.parametrize(
    "bad",
    [record(status=builds.BuildStatus.FAIL), record(kind=builds.ArtifactKind.QCOW2)],
)
def test_a_parent_that_did_not_complete_an_image_is_refused(bad: builds.BuildRecord) -> None:
    with pytest.raises(errors.Refusal) as raised:
        builds.require_frozen(bad, frozen(), manifest())

    assert raised.value.reason is refusals.RefusalReason.BUILD_PARENT_NOT_COMPLETE


def test_a_frozen_document_naming_another_manifest_is_refused() -> None:
    with pytest.raises(errors.Refusal) as raised:
        builds.require_frozen(record(), frozen(digest="d" * 64), manifest())

    assert raised.value.reason is refusals.RefusalReason.FROZEN_IMAGE_MISMATCH


def test_a_manifest_naming_another_image_is_refused() -> None:
    with pytest.raises(errors.Refusal) as raised:
        builds.require_frozen(record(), frozen(image_id="e" * 64), manifest())

    assert raised.value.reason is refusals.RefusalReason.FROZEN_IMAGE_MISMATCH


def test_a_record_round_trips_through_its_document() -> None:
    original = builds.BuildRecord(
        status=builds.BuildStatus.PASS,
        kind=builds.ArtifactKind.QCOW2,
        profile=builds.Profile.FEDORA,
        source=identifiers.Digest("a" * 64),
        remote=safepaths.RemotePath("/var/tmp/apex-run"),
        parent=identifiers.BuildId("b" * 32),
        test_access=False,
    )

    assert builds.BuildRecord.parse(json.dumps(original.document()).encode()) == original


@pytest.mark.parametrize(
    "payload",
    [
        b"nope",
        b"[]",
        b'{"status": "PASS"}',
        b'{"status": "MAYBE", "kind": "image", "profile": "fedora", "remote": "/r"}',
    ],
)
def test_a_damaged_record_is_refused(payload: bytes) -> None:
    with pytest.raises(errors.Refusal) as raised:
        builds.BuildRecord.parse(payload)

    assert raised.value.reason is refusals.RefusalReason.BUILD_RECORD_MALFORMED


def test_only_the_image_and_the_fingerprint_packages_are_not_derived() -> None:
    roots = {builds.ArtifactKind.IMAGE, builds.ArtifactKind.FINGERPRINT_RPMS}
    assert not any(kind.derived for kind in roots)
    assert all(kind.derived for kind in builds.ArtifactKind if kind not in roots)
    assert builds.ArtifactKind.FINGERPRINT_RPMS.packaged and not builds.ArtifactKind.QCOW2.packaged
    assert builds.ArtifactKind.FINGERPRINT_IMAGE.guest_script == "fingerprint-image.py"
    assert builds.ArtifactKind.QCOW2.guest_script == builds.ArtifactKind.INSTALLER.guest_script


def test_only_fedora_is_a_reviewed_profile() -> None:
    assert builds.Profile.FEDORA.reviewed
    assert not builds.Profile.CACHYOS.reviewed

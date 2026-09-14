"""What a build is asked for, what it records, and when a parent build may be built upon.

An artifact other than the image is derived from a completed image build. The parent is
accepted only when its record says it completed, its frozen document names the manifest that
is actually on disk, and that manifest names the image the document claims.
"""

from __future__ import annotations

import dataclasses
import enum
import json
from typing import Self

from apex.kernel import encoding, errors, hashing, identifiers, refusals, safepaths
from apex.model import oci

RECORD_NAME = "result.json"
OUTPUT_DIRECTORY = "output"
IMAGE_DOCUMENT = "image.json"
MANIFEST_DOCUMENT = "manifest.json"
TARGET_DOCUMENT = "target-image.json"
BUILD_LOG = "build.log"


class Profile(enum.StrEnum):
    FEDORA = "fedora"
    CACHYOS = "cachyos"

    @property
    def reviewed(self) -> bool:
        """CachyOS waits for a reviewed kernel source lock and matching modules."""
        return self is Profile.FEDORA


class ArtifactKind(enum.StrEnum):
    IMAGE = "image"
    QCOW2 = "qcow2"
    INSTALLER = "installer"
    LIVE = "live"
    NVIDIA = "nvidia"
    FINGERPRINT_RPMS = "fingerprint-rpms"
    FINGERPRINT_IMAGE = "fingerprint-image"

    @property
    def derived(self) -> bool:
        return self not in ROOT_KINDS

    @property
    def packaged(self) -> bool:
        """Built by the guest's own program over the payload, and signed by nobody."""
        return self in PACKAGE_KINDS

    @property
    def guest_script(self) -> str:
        return GUEST_SCRIPTS.get(self, "disk-artifact.sh")


ROOT_KINDS = frozenset({ArtifactKind.IMAGE, ArtifactKind.FINGERPRINT_RPMS})
PACKAGE_KINDS = frozenset({ArtifactKind.NVIDIA, ArtifactKind.FINGERPRINT_RPMS})
GUEST_SCRIPTS = {
    ArtifactKind.IMAGE: "build.sh",
    ArtifactKind.LIVE: "live-artifact.sh",
    ArtifactKind.NVIDIA: "nvidia-build.py",
    ArtifactKind.FINGERPRINT_RPMS: "fingerprint-rpms.py",
    ArtifactKind.FINGERPRINT_IMAGE: "fingerprint-image.py",
}


class BuildStatus(enum.StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


@dataclasses.dataclass(frozen=True, slots=True)
class BuildRecord:
    status: BuildStatus
    kind: ArtifactKind
    profile: Profile
    source: identifiers.Digest
    remote: safepaths.RemotePath
    parent: identifiers.BuildId | None
    test_access: bool

    def document(self) -> encoding.Document:
        return {
            "status": str(self.status),
            "kind": str(self.kind),
            "profile": str(self.profile),
            "source_sha256": self.source.hex,
            "remote": str(self.remote),
            "parent_build": None if self.parent is None else str(self.parent),
            "test_access": self.test_access,
        }

    @classmethod
    def parse(cls, payload: bytes) -> Self:
        reason = refusals.RefusalReason.BUILD_RECORD_MALFORMED
        try:
            document = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as fault:
            raise errors.Refusal(reason, subject="not a JSON document") from fault
        if not isinstance(document, dict):
            raise errors.Refusal(reason, subject="not an object")
        try:
            parent = document.get("parent_build")
            return cls(
                status=BuildStatus(str(document["status"])),
                kind=ArtifactKind(str(document["kind"])),
                profile=Profile(str(document["profile"])),
                source=identifiers.Digest(str(document["source_sha256"])),
                remote=safepaths.RemotePath(str(document["remote"])),
                parent=None if parent is None else identifiers.BuildId.parse(str(parent)),
                test_access=bool(document.get("test_access", False)),
            )
        except (KeyError, ValueError, errors.Refusal) as fault:
            raise errors.Refusal(reason, subject=str(fault)) from fault


def require_frozen(record: BuildRecord, image: oci.FrozenImage, manifest: bytes) -> oci.FrozenImage:
    """The parent build's image, once its three documents agree with one another."""
    if record.status is not BuildStatus.PASS or record.kind is not ArtifactKind.IMAGE:
        raise errors.Refusal(
            refusals.RefusalReason.BUILD_PARENT_NOT_COMPLETE,
            subject=f"the parent build is {record.status} {record.kind}",
            remedy="derive artifacts from a completed image build",
        )
    if image.digest != hashing.digest_bytes(manifest):
        raise errors.Refusal(
            refusals.RefusalReason.FROZEN_IMAGE_MISMATCH,
            subject="the frozen document names a manifest other than the one on disk",
        )
    if oci.config_digest(manifest) != image.image_id:
        raise errors.Refusal(
            refusals.RefusalReason.FROZEN_IMAGE_MISMATCH,
            subject="the manifest names an image other than the frozen document's",
        )
    return image

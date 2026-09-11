"""Verifying a signed bundle against an anchor the bundle did not supply.

The signature is checked over the bytes that are then parsed, so nothing can be swapped in
between. Every file the inventory names is hashed again, cold, and anything in the directory
the inventory does not name is a refusal, so an unsigned file cannot stand beside signed ones.
"""

from __future__ import annotations

import dataclasses

from apex.config import defaults
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.model import bundles, oci
from apex.ports import files, portset
from apex.trust import anchors

UNSIGNED_KINDS = frozenset({files.EntryKind.SYMLINK, files.EntryKind.OTHER})


@dataclasses.dataclass(frozen=True, slots=True)
class BundleLocation:
    root: safepaths.RuntimeRoot
    relative: str

    def directory(self) -> safepaths.SafePath:
        return self.root.child(self.relative)

    def entry(self, name: str) -> safepaths.SafePath:
        return self.root.child(f"{self.relative}/{name}")

    def regular_entry(self, name: str) -> safepaths.SafePath:
        return safepaths.SafePath.regular_file(self.entry(name).path, within=self.root)


@dataclasses.dataclass(frozen=True, slots=True)
class VerifiedBundle:
    location: BundleLocation
    manifest: bundles.ArtifactManifest
    anchor: anchors.TrustAnchor

    @property
    def digest(self) -> identifiers.Digest:
        return self.manifest.digest

    @property
    def files_verified(self) -> int:
        return len(self.manifest.files)


def verify_bundle(
    ports: portset.HostPorts, *, location: BundleLocation, anchor: anchors.TrustAnchor
) -> VerifiedBundle:
    anchors.require_independent(anchor, of=location.directory())
    payload = _document(ports, location, bundles.MANIFEST_NAME)
    signature = _document(ports, location, bundles.SIGNATURE_NAME)
    if not ports.signing.verify(payload=payload, signature=signature, public_key=anchor.public_key):
        raise errors.Refusal(
            refusals.RefusalReason.SIGNATURE_REJECTED,
            subject=location.relative,
            remedy="the inventory was not signed by the key this anchor holds",
        )
    manifest = bundles.ArtifactManifest.parse(payload)
    _refuse_unsigned_content(ports, location, manifest)
    _check_every_file(ports, location, manifest)
    _check_oci_binding(ports, location, manifest)
    return VerifiedBundle(location=location, manifest=manifest, anchor=anchor)


def _document(ports: portset.HostPorts, location: BundleLocation, name: str) -> bytes:
    return ports.files.read_bytes(location.regular_entry(name), limit=defaults.DOCUMENT_LIMIT.value)


def _refuse_unsigned_content(
    ports: portset.HostPorts, location: BundleLocation, manifest: bundles.ArtifactManifest
) -> None:
    permitted = manifest.permitted_paths()
    for entry in ports.files.list_tree(location.directory()):
        unsigned = entry.kind is files.EntryKind.REGULAR and entry.relative not in permitted
        if entry.kind in UNSIGNED_KINDS or unsigned:
            raise errors.Refusal(
                refusals.RefusalReason.BUNDLE_CONTENT_UNSIGNED,
                subject=entry.relative,
                remedy="the directory holds content the signed inventory does not name",
            )


def _digest_of(
    ports: portset.HostPorts, location: BundleLocation, name: str
) -> identifiers.Digest:
    return ports.digests.file(location.regular_entry(name))


def _check_every_file(
    ports: portset.HostPorts, location: BundleLocation, manifest: bundles.ArtifactManifest
) -> None:
    ports.digests.forget()
    for name, expected in manifest.files.items():
        if _digest_of(ports, location, name) != expected:
            raise errors.Refusal(refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH, subject=name)


def _check_oci_binding(
    ports: portset.HostPorts, location: BundleLocation, manifest: bundles.ArtifactManifest
) -> None:
    for name in manifest.oci_manifest_names():
        if _digest_of(ports, location, name) != manifest.digest:
            raise errors.Refusal(
                refusals.RefusalReason.SIGNED_DIGEST_MISMATCH,
                subject=name,
                remedy="the signed digest does not match the packaged OCI manifest",
            )
    if bundles.IMAGE_DOCUMENT_NAME not in manifest.files:
        return
    image = oci.FrozenImage.parse(_document(ports, location, bundles.IMAGE_DOCUMENT_NAME))
    oci_manifest = bundles.OCI_MANIFEST_NAMES[0]
    if image.digest != manifest.digest:
        raise errors.Refusal(
            refusals.RefusalReason.IMAGE_METADATA_MISMATCH,
            subject=f"{bundles.IMAGE_DOCUMENT_NAME} names another digest",
        )
    if oci_manifest not in manifest.files:
        raise errors.Refusal(
            refusals.RefusalReason.IMAGE_METADATA_MISMATCH,
            subject=f"{oci_manifest} is not in the inventory",
        )
    if oci.config_digest(_document(ports, location, oci_manifest)) != image.image_id:
        raise errors.Refusal(
            refusals.RefusalReason.IMAGE_METADATA_MISMATCH,
            subject="the image metadata does not match the OCI configuration",
        )

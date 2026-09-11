"""A payload that no longer matches its signed digest must be refused by checksum."""

from __future__ import annotations

from apex.kernel import identifiers, refusals
from apex.model import bundles
from apex.ports import portset
from apex.trust import negatives, tampering, verifying

STAND_IN = b"intentionally invalid test payload"


def prepare(
    ports: portset.HostPorts, *, original: negatives.Trial, scratch: verifying.BundleLocation
) -> negatives.Trial:
    manifest = bundles.ArtifactManifest.parse(
        tampering.copy_headers(ports, source=original.location, target=scratch)
    )
    first = next(iter(manifest.files))
    tampering.write_entry(ports, target=scratch, name=first, payload=STAND_IN)
    return negatives.Trial(location=scratch, anchor=original.anchor)


negatives.declare(
    negatives.Negative(
        id=identifiers.FaultId("trust.changed-payload"),
        expects=refusals.RefusalReason.ARTIFACT_CHECKSUM_MISMATCH,
        prepare=prepare,
    )
)

"""An inventory altered after signing must fail the signature, whatever else is intact."""

from __future__ import annotations

from apex.kernel import identifiers, refusals
from apex.model import bundles
from apex.ports import portset
from apex.trust import negatives, tampering, verifying


def prepare(
    ports: portset.HostPorts, *, original: negatives.Trial, scratch: verifying.BundleLocation
) -> negatives.Trial:
    manifest = tampering.copy_headers(ports, source=original.location, target=scratch)
    tampering.write_entry(
        ports, target=scratch, name=bundles.MANIFEST_NAME, payload=b"X" + manifest[1:]
    )
    return negatives.Trial(location=scratch, anchor=original.anchor)


negatives.declare(
    negatives.Negative(
        id=identifiers.FaultId("trust.changed-manifest"),
        expects=refusals.RefusalReason.SIGNATURE_REJECTED,
        prepare=prepare,
    )
)

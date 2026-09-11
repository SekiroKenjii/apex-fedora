"""The key shipped inside a bundle must never be accepted as the anchor for that bundle."""

from __future__ import annotations

from apex.kernel import identifiers, refusals
from apex.model import bundles
from apex.ports import portset
from apex.trust import anchors, negatives, tampering, verifying


def prepare(
    ports: portset.HostPorts, *, original: negatives.Trial, scratch: verifying.BundleLocation
) -> negatives.Trial:
    tampering.copy_headers(ports, source=original.location, target=scratch)
    tampering.write_entry(
        ports,
        target=scratch,
        name=bundles.BUNDLED_KEY_NAME,
        payload=original.anchor.public_key.path.read_bytes(),
    )
    shipped = anchors.operator_supplied(scratch.entry(bundles.BUNDLED_KEY_NAME).path)
    return negatives.Trial(location=scratch, anchor=shipped)


negatives.declare(
    negatives.Negative(
        id=identifiers.FaultId("trust.bundled-key"),
        expects=refusals.RefusalReason.TRUST_ANCHOR_FROM_BUNDLE,
        prepare=prepare,
    )
)

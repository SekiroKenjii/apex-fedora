"""A key nobody trusts must not verify the bundle, however well formed the bundle is."""

from __future__ import annotations

from apex.kernel import identifiers, refusals, safepaths
from apex.ports import portset
from apex.trust import anchors, negatives, verifying

PRIVATE_NAME = "wrong.key"
PUBLIC_NAME = "wrong.pub"


def prepare(
    ports: portset.HostPorts, *, original: negatives.Trial, scratch: verifying.BundleLocation
) -> negatives.Trial:
    ports.signing.generate_key_pair(
        private_into=scratch.entry(PRIVATE_NAME), public_into=scratch.entry(PUBLIC_NAME)
    )
    stranger = anchors.TrustAnchor(
        public_key=safepaths.RegularFile.adopt(scratch.entry(PUBLIC_NAME).path),
        provenance=anchors.Provenance.OPERATOR_SUPPLIED,
    )
    return negatives.Trial(location=original.location, anchor=stranger)


negatives.declare(
    negatives.Negative(
        id=identifiers.FaultId("trust.untrusted-key"),
        expects=refusals.RefusalReason.SIGNATURE_REJECTED,
        prepare=prepare,
    )
)

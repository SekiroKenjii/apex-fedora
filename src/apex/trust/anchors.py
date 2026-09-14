"""A trust anchor: a public key and where it came from.

Provenance is a field, so an anchor read out of the bundle it is meant to judge cannot be
constructed, and a key that happens to sit inside the bundle directory is refused before
anything is verified against it.
"""

from __future__ import annotations

import dataclasses
import enum
from pathlib import Path

from apex.kernel import errors, refusals, safepaths


class Provenance(enum.StrEnum):
    OPERATOR_SUPPLIED = "operator-supplied"
    BUILDER_SSH = "builder-ssh"
    BUNDLE = "bundle"


@dataclasses.dataclass(frozen=True, slots=True)
class TrustAnchor:
    public_key: safepaths.RegularFile
    provenance: Provenance

    def __post_init__(self) -> None:
        if self.provenance is Provenance.BUNDLE:
            raise errors.Refusal(
                refusals.RefusalReason.TRUST_ANCHOR_FROM_BUNDLE,
                subject=str(self.public_key),
                remedy="a bundle cannot establish its own trust; use a key checked out of band",
            )


def operator_supplied(candidate: Path) -> TrustAnchor:
    return TrustAnchor(
        public_key=safepaths.RegularFile.adopt(candidate), provenance=Provenance.OPERATOR_SUPPLIED
    )


def require_independent(anchor: TrustAnchor, *, of: safepaths.SafePath) -> None:
    """Refuse an anchor that lives inside the directory it is asked to judge."""
    if anchor.public_key.path.is_relative_to(of.path.resolve()):
        raise errors.Refusal(
            refusals.RefusalReason.TRUST_ANCHOR_FROM_BUNDLE,
            subject=str(anchor.public_key),
            remedy="select an independently trusted key, not one supplied with the artifact",
        )

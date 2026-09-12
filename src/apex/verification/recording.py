"""The store and the chain a run records into, handed to the stage that mints.

A stage cannot open the store itself: the location and the chain's key are the operator's,
so the composition root builds this once and seeds it, and the stage only ever appends.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from apex.attestation import ledger, minting, proofs
from apex.kernel import claims, identifiers, verdicts


@dataclasses.dataclass(frozen=True, slots=True)
class Recorded:
    check: identifiers.CheckId
    verdict: verdicts.Verdict
    sequence: int
    proofs: tuple[identifiers.Digest, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class Recorder:
    store: proofs.ProofStore
    chain: ledger.Ledger

    def record(
        self,
        *,
        check: identifiers.CheckId,
        verdict: verdicts.Verdict,
        offered: Sequence[minting.Offered],
        candidate: identifiers.Digest,
        witnessed: claims.EnvironmentKind,
    ) -> Recorded:
        minted = minting.mint(
            check=check,
            verdict=verdict,
            offered=offered,
            candidate=candidate,
            witnessed=witnessed,
            store=self.store,
            chain=self.chain,
        )
        return Recorded(
            check=check,
            verdict=verdict,
            sequence=minted.sealed.entry.sequence,
            proofs=tuple(proof.digest for proof in minted.proofs),
        )

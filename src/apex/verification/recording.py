"""The store and the chain a run records into, handed to the stage that mints.

A stage cannot open the store itself: the location and the chain's key are the operator's,
so the composition root builds this once and seeds it, and the stage only ever appends.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path

from apex.attestation import ledger, minting, proofs
from apex.config import defaults
from apex.kernel import claims, errors, identifiers, refusals, safepaths, secrets, verdicts
from apex.model import storemark
from apex.ports import clock, files, ids


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

    @classmethod
    def open(
        cls,
        root: safepaths.RuntimeRoot,
        *,
        filesystem: files.FileSystemPort,
        identities: ids.IdentityPort,
        clock: clock.ClockPort,
    ) -> Recorder:
        """Mark the root as version two and lay down the key, once; then continue the chain.

        A version one store becomes version two by this mark alone: its documents stay where
        they are and are read as imported beside the chain. A later version is refused.
        """
        _require_mark(root, filesystem)
        location = proofs.StoreLocation(root=root)
        signer = ledger.signer_at(location, filesystem)
        if signer is None:
            material = f"{identities.token()}{identities.token()}"
            filesystem.write_atomic(
                location.key_path(), material.encode(), mode=defaults.RECORD_MODE
            )
            signer = ledger.ChainSigner(secrets.Secret(material))
        return cls(
            store=proofs.ProofStore(location=location, filesystem=filesystem),
            chain=ledger.Ledger(
                location=location, filesystem=filesystem, signer=signer, clock=clock
            ),
        )

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


def _require_mark(root: safepaths.RuntimeRoot, filesystem: files.FileSystemPort) -> None:
    mark = storemark.read_mark(Path(root.path))
    if isinstance(mark, storemark.Unreadable):
        raise errors.Refusal(
            refusals.RefusalReason.MALFORMED_STORE_MARK,
            subject=f"{storemark.MARK_NAME}: {mark.detail}",
            remedy="absence means version one; corruption means nothing at all",
        )
    if isinstance(mark, storemark.Marked) and mark.version > storemark.SECOND_VERSION:
        raise errors.PreconditionUnmet(
            refusals.RefusalReason.STORE_VERSION_NOT_SUPPORTED,
            subject=f"mark:{mark.version}; this build writes {storemark.SECOND_VERSION}",
        )
    if isinstance(mark, storemark.Marked) and mark.version == storemark.SECOND_VERSION:
        return
    filesystem.write_atomic(
        root.child(storemark.MARK_NAME),
        storemark.document(storemark.SECOND_VERSION),
        mode=defaults.RECORD_MODE,
    )

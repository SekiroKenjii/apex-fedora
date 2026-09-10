"""Proofs named by their own content.

The v1 store names a proof by a path chosen when the record is written, so the bytes behind a
passing record can be replaced without touching the record. Here the name is the digest. An
altered proof is a different object, and the citation stops resolving.

The store never lives in the legacy directory. Selecting a candidate in v1 renames that whole
directory into an archive, which would carry any store placed inside it away with it.
"""

from __future__ import annotations

import dataclasses

from apex.kernel import errors, hashing, identifiers, quantities, refusals, safepaths
from apex.ports import files
from apex.registry import descriptors

OBJECT_DIRECTORY = "objects"
LEDGER_DIRECTORY = "ledger"
CHAIN_NAME = "chain.jsonl"
HEAD_NAME = "head.json"
FAN_OUT = 2
LEGACY_AREA = "evidence"
DEFAULT_AREA = "attestation"
OBJECT_MODE = quantities.FileMode(0o600)
OVERREAD = 1


def address(payload: bytes) -> identifiers.Digest:
    return hashing.digest_bytes(payload)


@dataclasses.dataclass(frozen=True, slots=True)
class Proof:
    digest: identifiers.Digest
    kind: str
    byte_count: int

    def __post_init__(self) -> None:
        if self.kind not in descriptors.PERMITTED_PROOF_KINDS:
            raise errors.Refusal(
                refusals.RefusalReason.PROOF_KIND_NOT_ACCEPTED,
                subject=self.kind,
                remedy="a proof is text, JSON, an image or a report, never a template",
            )
        if self.byte_count <= 0:
            raise errors.Refusal(
                refusals.RefusalReason.PROOF_IS_EMPTY,
                subject=self.digest.hex,
                remedy="an empty file establishes nothing",
            )


@dataclasses.dataclass(frozen=True, slots=True)
class StoreLocation:
    root: safepaths.RuntimeRoot
    area: str = DEFAULT_AREA

    def __post_init__(self) -> None:
        if self.area == LEGACY_AREA or "/" in self.area or not self.area:
            raise errors.Refusal(
                refusals.RefusalReason.STORE_AREA_NOT_PERMITTED,
                subject=self.area,
                remedy="the store is a single directory beside the legacy tree, never inside it",
            )

    def object_path(self, digest: identifiers.Digest) -> safepaths.SafePath:
        return self.root.child(
            f"{self.area}/{OBJECT_DIRECTORY}/{digest.hex[:FAN_OUT]}/{digest.hex}"
        )

    def chain_path(self) -> safepaths.SafePath:
        return self.root.child(f"{self.area}/{LEDGER_DIRECTORY}/{CHAIN_NAME}")

    def head_path(self) -> safepaths.SafePath:
        return self.root.child(f"{self.area}/{LEDGER_DIRECTORY}/{HEAD_NAME}")


class ProofStore:
    """Absorb bytes, hand back a citation, and refuse to return anything that changed."""

    def __init__(
        self, *, location: StoreLocation, filesystem: files.FileSystemPort
    ) -> None:
        self._location = location
        self._files = filesystem
        self.absorbed = 0

    def absorb(self, payload: bytes, *, kind: str) -> Proof:
        proof = Proof(digest=address(payload), kind=kind, byte_count=len(payload))
        target = self._location.object_path(proof.digest)
        if self._files.exists(target):
            return proof
        self._files.write_atomic(target, payload, mode=OBJECT_MODE)
        self.absorbed += 1
        return proof

    def holds(self, proof: Proof) -> bool:
        return self._files.exists(self._location.object_path(proof.digest))

    def load(self, proof: Proof) -> bytes:
        """Return the bytes only if they still hash to the name they are filed under.

        The read asks for one byte more than the record claims. Bounding it at exactly the
        recorded length would silently truncate an object that grew, and the surviving prefix
        would hash correctly, so appended bytes would pass while every other reader saw them.
        """
        target = self._location.object_path(proof.digest)
        payload = self._files.read_bytes(target, limit=proof.byte_count + OVERREAD)
        if len(payload) != proof.byte_count or address(payload) != proof.digest:
            raise errors.Refusal(
                refusals.RefusalReason.PROOF_ALTERED,
                subject=proof.digest.hex,
                remedy="the object no longer hashes to its own name",
            )
        return payload

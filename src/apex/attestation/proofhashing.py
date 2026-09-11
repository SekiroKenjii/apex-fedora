"""Turn one stored document into a resolved record, re-hashing every proof it cites.

The re-hash happens on every call with no cache. A digest trusted from metadata is a digest an
editor can change, so the cost of reading the bytes again is the price of the answer.

`imported` is a required keyword. A default here would be the single character that silently
unmarks every record in the store.
"""

from __future__ import annotations

from pathlib import Path

from apex.attestation import readiness
from apex.kernel import hashing
from apex.model import runtimestate


def proofs_intact(record: runtimestate.StoredRecord, *, evidence_root: Path) -> bool:
    for proof in record.proofs:
        target = evidence_root / proof.relative_path
        if target.is_symlink() or not target.is_file():
            return False
        if not target.resolve().is_relative_to(evidence_root.resolve()):
            return False
        with target.open("rb") as handle:
            observed = hashing.digest_stream(iter(lambda: handle.read(hashing.READ_CHUNK), b""))
        if observed != proof.digest:
            return False
    return True


def resolve(
    stored: runtimestate.StoredRecord, *, evidence_root: Path, imported: bool
) -> readiness.ResolvedRecord:
    return readiness.ResolvedRecord(
        check=stored.check,
        verdict=stored.verdict,
        environment=stored.environment,
        candidate=stored.digest,
        proofs_intact=proofs_intact(stored, evidence_root=evidence_root),
        proof_count=len(stored.proofs),
        imported=imported,
    )

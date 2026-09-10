"""Turn the stored v1 documents into resolved records the fold can decide on.

Every cited proof is re-hashed here, on every call, with no cache. That is the one integrity
property the current code genuinely has, and it is not a performance defect to remove: a
digest trusted from metadata is a digest an editor can change.
"""

from __future__ import annotations

from pathlib import Path

from apex.attestation import catalogue, readiness
from apex.kernel import claims, hashing, identifiers
from apex.model import runtimestate


def _proofs_intact(record: runtimestate.StoredRecord, evidence_root: Path) -> bool:
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
    stored: runtimestate.StoredRecord, *, evidence_root: Path, imported: bool = False
) -> readiness.ResolvedRecord:
    return readiness.ResolvedRecord(
        check=stored.check,
        verdict=stored.verdict,
        environment=stored.environment,
        candidate=stored.digest,
        proofs_intact=_proofs_intact(stored, evidence_root),
        proof_count=len(stored.proofs),
        imported=imported,
    )


def resolve_store(runtime_root: Path) -> tuple[
    tuple[readiness.ResolvedRecord, ...], identifiers.Digest | None
]:
    evidence_root = runtime_root / "evidence"
    candidate_document = runtime_root / "candidate.json"
    candidate = (
        runtimestate.read_candidate(candidate_document).digest
        if candidate_document.is_file()
        else None
    )
    records = tuple(
        resolve(stored, evidence_root=evidence_root)
        for stored in runtimestate.read_evidence_directory(evidence_root)
    )
    return records, candidate


def required_environments() -> dict[str, claims.EnvironmentKind]:
    return {str(spec.id): spec.environment for spec in catalogue.sealed().values()}

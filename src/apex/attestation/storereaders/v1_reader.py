"""The store the pre-restructure tools wrote.

Absence of a mark elects this reader, and an explicit version one elects it too. Nothing here
is proven by a port and nothing was read back off the artifact, so every record it produces
carries both permanent limits for as long as it exists.

A record that cannot be read becomes a named fault and the rest of the store still resolves.
Refusing the whole store because one document is damaged would hide every result beside it.
"""

from __future__ import annotations

from pathlib import Path

from apex.attestation import (
    attesting,
    ledger,
    markclaims,
    proofhashing,
    readerspecs,
    storereaders,
)
from apex.kernel import errors, refusals
from apex.model import runtimestate, storemark
from apex.ports import files as files_port

VERSION = storemark.FIRST_VERSION


def _fault(reason: refusals.RefusalReason, subject: str) -> str:
    return f"{reason.value}: {subject}"


def read(
    runtime_root: Path,
    *,
    spec: readerspecs.StoreReaderSpec,
    files: files_port.FileSystemPort,  # noqa: ARG001
) -> readerspecs.StoreReading:
    # The legacy documents are read where they lie, by the model's own readers; the port
    # arrived with the store that is written through it and this reader has no use for it.
    evidence_root = runtime_root / runtimestate.EVIDENCE_DIRECTORY
    document = runtime_root / runtimestate.CANDIDATE_NAME
    candidate = (
        runtimestate.read_candidate(document).digest if document.is_file() else None
    )
    faults: list[str] = []
    attestations: list[attesting.Attestation] = []
    imported = spec.kind is ledger.EntryKind.IMPORTED
    if evidence_root.is_dir():
        for path in sorted(evidence_root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                faults.append(
                    _fault(refusals.RefusalReason.PATH_IS_A_SYMLINK, f"{path.name} is not a record")
                )
                continue
            try:
                stored = runtimestate.read_evidence_record(path)
            except errors.Refusal as refusal:
                faults.append(_fault(refusal.reason, path.name))
                continue
            if candidate is None:
                faults.append(
                    _fault(
                        refusals.RefusalReason.STALE_EVIDENCE,
                        f"{path.name} names a build this root has no candidate for",
                    )
                )
                continue
            attestations.append(
                attesting.Attestation(
                    kind=spec.kind,
                    resolved=proofhashing.resolve(
                        stored, evidence_root=evidence_root, imported=imported
                    ),
                    limits=spec.limits,
                    origin=path.name,
                )
            )
    return readerspecs.StoreReading(
        version=spec.version,
        attestations=tuple(attestations),
        candidate=candidate,
        faults=tuple(faults),
    )


SPEC = storereaders.declare(
    readerspecs.StoreReaderSpec(
        version=VERSION,
        marks=(markclaims.MarkAbsent(), markclaims.MarkEquals(VERSION)),
        read=read,
        limits=attesting.LEGACY_LIMITS,
        reads_history=False,
        reads_archives=False,
    )
)

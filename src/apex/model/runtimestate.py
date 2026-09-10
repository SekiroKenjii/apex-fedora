"""Readers for the documents the pre-restructure tools wrote.

Absence of a schema stamp means version one. Nothing here writes, renames or repairs: the
stored evidence is the only irreplaceable thing in the project, so it is read where it lies.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from pathlib import Path

from apex.kernel import claims, errors, identifiers, refusals, verdicts

EVIDENCE_HISTORY_DIRECTORY = "history"


@dataclasses.dataclass(frozen=True, slots=True)
class ProofReference:
    relative_path: str
    digest: identifiers.Digest


@dataclasses.dataclass(frozen=True, slots=True)
class StoredCandidate:
    digest: identifiers.Digest
    build: identifiers.BuildId
    verification: Mapping[str, object]


@dataclasses.dataclass(frozen=True, slots=True)
class StoredRecord:
    check: identifiers.CheckId
    digest: identifiers.Digest
    verdict: verdicts.Verdict
    environment: claims.EnvironmentKind
    description: str
    recorded_at: str
    reason: str
    proofs: tuple[ProofReference, ...]


@dataclasses.dataclass(frozen=True, slots=True)
class ArchivedCandidate:
    directory: Path
    candidate: StoredCandidate
    records: tuple[StoredRecord, ...]


def _document(path: Path) -> Mapping[str, object]:
    try:
        loaded = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise errors.Refusal(
            refusals.RefusalReason.MALFORMED_IDENTIFIER, subject=f"{path.name}: {error.msg}"
        ) from error
    if not isinstance(loaded, dict):
        raise errors.Refusal(
            refusals.RefusalReason.MALFORMED_IDENTIFIER, subject=f"{path.name} is not an object"
        )
    return loaded


def _environment(document: Mapping[str, object], path: Path) -> tuple[claims.EnvironmentKind, str]:
    raw = document.get("environment")
    if not isinstance(raw, dict):
        raise errors.Refusal(
            refusals.RefusalReason.MALFORMED_IDENTIFIER, subject=f"{path.name} has no environment"
        )
    try:
        kind = claims.EnvironmentKind(str(raw.get("kind")))
    except ValueError as error:
        raise errors.Refusal(
            refusals.RefusalReason.MALFORMED_IDENTIFIER,
            subject=f"{path.name}: unknown environment {raw.get('kind')!r}",
        ) from error
    return kind, str(raw.get("description", ""))


def read_candidate(path: Path) -> StoredCandidate:
    document = _document(path)
    verification = document.get("verification")
    return StoredCandidate(
        digest=identifiers.Digest.parse(str(document.get("digest", ""))),
        build=identifiers.BuildId.parse(str(document.get("build_id", ""))),
        verification=verification if isinstance(verification, dict) else {},
    )


def read_evidence_record(path: Path) -> StoredRecord:
    document = _document(path)
    kind, description = _environment(document, path)
    proofs = document.get("proof")
    references = tuple(
        ProofReference(
            relative_path=str(item["path"]),
            digest=identifiers.Digest.parse(str(item["sha256"])),
        )
        for item in (proofs if isinstance(proofs, list) else [])
    )
    return StoredRecord(
        check=identifiers.CheckId(str(document.get("check", ""))),
        digest=identifiers.Digest.parse(str(document.get("digest", ""))),
        verdict=verdicts.parse(
            str(document.get("status", "")), reason=refusals.RefusalReason.NO_VERIFIED_RESULT
        ),
        environment=kind,
        description=description,
        recorded_at=str(document.get("recorded_at", "")),
        reason=str(document.get("reason", "")),
        proofs=references,
    )


def read_evidence_directory(directory: Path) -> tuple[StoredRecord, ...]:
    if not directory.is_dir():
        return ()
    return tuple(
        read_evidence_record(path)
        for path in sorted(directory.glob("*.json"))
        if path.is_file() and not path.is_symlink()
    )


def read_candidate_history(directory: Path) -> tuple[ArchivedCandidate, ...]:
    if not directory.is_dir():
        return ()
    archives = []
    for archive in sorted(path for path in directory.iterdir() if path.is_dir()):
        candidate = archive / "candidate.json"
        if not candidate.is_file():
            continue
        archives.append(
            ArchivedCandidate(
                directory=archive,
                candidate=read_candidate(candidate),
                records=read_evidence_directory(archive / "evidence"),
            )
        )
    return tuple(archives)

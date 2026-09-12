"""The store this code writes: the chain beside the documents the older tools left.

A version two mark elects this reader. It reads the legacy documents exactly as the version
one reader does, because they are still there and still imported, and then the chain, whose
entries were witnessed by ports and carry no permanent limit. Where a check has both, the
chain's latest entry is the result and the imported one is superseded.

A chain that does not replay is a named fault at the sequence where it breaks; the entries
before the break each carried their own tag and link and still count. A chain with no key
beside it cannot be confirmed at all, and says so rather than counting anything.
"""

from __future__ import annotations

from pathlib import Path

from apex.attestation import (
    attesting,
    ledger,
    markclaims,
    proofs,
    readerspecs,
    readiness,
    storereaders,
)
from apex.attestation.storereaders import v1_reader
from apex.kernel import refusals, safepaths
from apex.model import storemark
from apex.ports import files as files_port

VERSION = storemark.SECOND_VERSION
ORIGIN = "chain#{sequence}"


def _fault(reason: refusals.RefusalReason, subject: str) -> str:
    return f"{reason.value}: {subject}"


def _chain(
    location: proofs.StoreLocation, files: files_port.FileSystemPort
) -> tuple[tuple[attesting.Attestation, ...], tuple[str, ...]]:
    if not files.exists(location.chain_path()):
        return (), ()
    signer = ledger.signer_at(location, files)
    if signer is None:
        return (), (
            _fault(refusals.RefusalReason.STALE_EVIDENCE, "the chain has no key beside it"),
        )
    lines, head = ledger.read_chain(location, files)
    entries, report = ledger.verified(lines, signer=signer, head=head)
    faults: list[str] = []
    if report.first_break is not None:
        faults.append(
            _fault(
                refusals.RefusalReason.STALE_EVIDENCE,
                f"the chain breaks at sequence {report.first_break.sequence}: "
                f"{report.first_break.cause}",
            )
        )
    latest: dict[str, ledger.Sealed] = {}
    for sealed in entries:
        latest[str(sealed.entry.event.check)] = sealed
    store = proofs.ProofStore(location=location, filesystem=files)
    return tuple(_attestation(sealed, store) for sealed in latest.values()), tuple(faults)


def _attestation(sealed: ledger.Sealed, store: proofs.ProofStore) -> attesting.Attestation:
    event = sealed.entry.event
    return attesting.Attestation(
        kind=ledger.EntryKind.RECORDED,
        resolved=readiness.ResolvedRecord(
            check=event.check,
            verdict=event.verdict,
            environment=event.environment,
            candidate=event.candidate,
            proofs_intact=all(store.intact(digest) for digest in event.proofs),
            proof_count=len(event.proofs),
            imported=False,
        ),
        limits=frozenset(event.scope_limits),
        origin=ORIGIN.format(sequence=sealed.entry.sequence),
    )


def read(
    runtime_root: Path,
    *,
    spec: readerspecs.StoreReaderSpec,
    files: files_port.FileSystemPort,
) -> readerspecs.StoreReading:
    legacy = v1_reader.read(runtime_root, spec=v1_reader.SPEC, files=files)
    location = proofs.StoreLocation(root=safepaths.RuntimeRoot.adopt(runtime_root))
    recorded, chain_faults = _chain(location, files)
    by_check = {item.check: item for item in legacy.attestations}
    for item in recorded:
        by_check[item.check] = item
    return readerspecs.StoreReading(
        version=spec.version,
        attestations=tuple(by_check[name] for name in sorted(by_check)),
        candidate=legacy.candidate,
        faults=legacy.faults + chain_faults,
    )


SPEC = storereaders.declare(
    readerspecs.StoreReaderSpec(
        version=VERSION,
        marks=(markclaims.MarkEquals(VERSION),),
        read=read,
        limits=frozenset(),
        reads_history=False,
        reads_archives=False,
    )
)

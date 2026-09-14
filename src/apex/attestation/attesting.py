"""What an imported record is, and what importing permanently costs it.

Two limits are properties of the v1 format rather than of any single record. Its environment
came from an argument instead of from the port that ran the check, and its binding to a
candidate was never read back off the artifact. Re-hashing the proofs retires neither.

The three checks below are defects rather than refusals: they can only fail because a reader
unit is wrong, never because the store on disk is.
"""

from __future__ import annotations

import dataclasses

from apex.attestation import ledger, readiness
from apex.kernel import claims, errors

LEGACY_LIMITS = frozenset(
    {claims.ScopeLimit.LEGACY_NO_PORT_PROOF, claims.ScopeLimit.LEGACY_NO_CANDIDATE_READBACK}
)


@dataclasses.dataclass(frozen=True, slots=True)
class Attestation:
    kind: ledger.EntryKind
    resolved: readiness.ResolvedRecord
    limits: frozenset[claims.ScopeLimit]
    origin: str

    def __post_init__(self) -> None:
        imported = self.kind is ledger.EntryKind.IMPORTED
        if imported != self.resolved.imported:
            raise errors.InternalDefect(
                f"{self.resolved.check}: kind {self.kind} does not match the record"
            )
        if imported and not self.limits >= LEGACY_LIMITS:
            raise errors.InternalDefect(
                f"{self.resolved.check}: an imported record cannot drop a permanent limit"
            )
        if not imported and self.limits & LEGACY_LIMITS:
            raise errors.InternalDefect(
                f"{self.resolved.check}: only an imported record carries a legacy limit"
            )

    @property
    def check(self) -> str:
        return str(self.resolved.check)

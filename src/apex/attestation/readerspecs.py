"""How a store reader declares what it claims and what it cannot prove.

The declaration is handed back to the reader's own function, so a reader stamps its declared
kind and limits onto every record it produces rather than repeating them as constants. The two
can then never drift apart.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from apex.attestation import attesting, ledger, markclaims, readiness
from apex.kernel import claims, errors, identifiers
from apex.model import storemark
from apex.ports import files


class ReadStore(Protocol):
    def __call__(
        self, runtime_root: Path, *, spec: StoreReaderSpec, files: files.FileSystemPort
    ) -> StoreReading: ...


@dataclasses.dataclass(frozen=True, slots=True)
class StoreReading:
    version: int
    attestations: tuple[attesting.Attestation, ...]
    candidate: identifiers.Digest | None
    faults: tuple[str, ...]

    @property
    def records(self) -> tuple[readiness.ResolvedRecord, ...]:
        return tuple(item.resolved for item in self.attestations)


@dataclasses.dataclass(frozen=True, slots=True)
class StoreReaderSpec:
    version: int
    marks: Sequence[markclaims.MarkClaim]
    read: ReadStore
    limits: frozenset[claims.ScopeLimit]
    reads_history: bool
    reads_archives: bool

    def __post_init__(self) -> None:
        if not self.marks:
            raise errors.RegistrationError(
                f"version {self.version}: a reader that claims no mark can never be elected"
            )
        if self.version < storemark.FIRST_VERSION:
            raise errors.RegistrationError(f"{self.version} is not a store version")
        if self.reads_history or self.reads_archives:
            raise errors.RegistrationError(
                f"version {self.version}: no reader may widen its scope until the fold's "
                "duplicate and binding rules are extended"
            )

    @property
    def kind(self) -> ledger.EntryKind:
        """A reader that cannot prove everything produces imported records, by construction."""
        return ledger.EntryKind.IMPORTED if self.limits else ledger.EntryKind.RECORDED

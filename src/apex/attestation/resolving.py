"""The shape the shadow gate reads, over the versioned reader beneath it.

This exists only while the pre-restructure fold is still the authority. Its callers want a
records-and-candidate pair; the reading carries more than that, including the store version and
every fault, which is why `just readiness-table` exists beside the shadow. At cutover the
callers move to `reading.read_store` and this module goes.
"""

from __future__ import annotations

from pathlib import Path

from apex.attestation import catalogue, readiness, reading
from apex.kernel import claims, identifiers


def resolve_store(runtime_root: Path) -> tuple[
    tuple[readiness.ResolvedRecord, ...], identifiers.Digest | None
]:
    found = reading.read_store(runtime_root)
    return found.records, found.candidate


def required_environments() -> dict[str, claims.EnvironmentKind]:
    return {str(spec.id): spec.environment for spec in catalogue.sealed().values()}

"""The separate column, as a type.

Where a record came from is a field on every row. The table is the only place the new fold
reaches an operator, so it carries the faults from both the reading and the fold: a duplicate
record, an unknown check or an altered proof would otherwise leave no trace in the one view
this phase adds.
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Mapping, Sequence

from apex.attestation import attesting, ledger, readerspecs, readiness, retracting
from apex.kernel import claims, encoding, verdicts


class Origin(enum.StrEnum):
    IMPORTED = "imported"
    RECORDED = "recorded"
    ABSENT = "absent"


@dataclasses.dataclass(frozen=True, slots=True)
class Row:
    check: str
    verdict: verdicts.Verdict
    origin: Origin
    limits: tuple[claims.ScopeLimit, ...]
    withheld: verdicts.Verdict | None


@dataclasses.dataclass(frozen=True, slots=True)
class Table:
    version: int
    strict: bool
    ready: bool
    imported: int
    counts: Mapping[str, int]
    rows: tuple[Row, ...]
    faults: tuple[str, ...]


def tabulate(
    *,
    reading: readerspecs.StoreReading,
    outcome: readiness.Outcome,
    withheld: Sequence[retracting.Withheld],
    strict: bool,
) -> Table:
    by_check = {item.check: item for item in reading.attestations}
    stated_before = {item.check: item.stated for item in withheld}
    rows = tuple(
        Row(
            check=name,
            verdict=outcome.verdict_of(name),
            origin=_origin(by_check.get(name)),
            limits=tuple(sorted(by_check[name].limits)) if name in by_check else (),
            withheld=stated_before.get(name),
        )
        for name in sorted(outcome.verdicts)
    )
    return Table(
        version=reading.version,
        strict=strict,
        ready=outcome.ready,
        imported=sum(1 for row in rows if row.origin is Origin.IMPORTED),
        counts=outcome.counts,
        rows=rows,
        faults=outcome.faults + reading.faults,
    )


def _origin(found: attesting.Attestation | None) -> Origin:
    if found is None:
        return Origin.ABSENT
    if found.kind is ledger.EntryKind.RECORDED:
        return Origin.RECORDED
    return Origin.IMPORTED


def document(table: Table) -> encoding.Document:
    return {
        "version": table.version,
        "strict": table.strict,
        "ready": table.ready,
        "imported": table.imported,
        "counts": dict(sorted(table.counts.items())),
        "checks": [
            {
                "check": row.check,
                "verdict": row.verdict.stored_name,
                "origin": str(row.origin),
                "limits": [str(limit) for limit in row.limits],
                "withheld": row.withheld.stored_name if row.withheld else None,
            }
            for row in table.rows
        ],
        "faults": list(table.faults),
    }

"""Strict readiness withholds a claim; it never erases a finding.

The plan words this as treating every imported record as not tested. Applied literally that
also demotes a blocked record, and blocked is what a detected fault looks like: an altered
proof, a record bound to another build, a pass with no proof behind it. `readiness._judge`
exists so a fault cannot look like a check nobody ran, so strict narrows to verdicts that
permit installation and leaves every finding exactly where the default fold put it.

Iteration is over the outcome, never over the imported set. The fold drops a record whose check
is outside the catalogue, so its name never reaches the verdict map, and indexing by it would
raise out of a command rather than answer.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from apex.attestation import attesting, ledger, readiness
from apex.kernel import refusals, verdicts

WITHHELD_REASON = refusals.RefusalReason.LEGACY_IMPORT_NOT_REPROVEN


@dataclasses.dataclass(frozen=True, slots=True)
class Withheld:
    check: str
    stated: verdicts.Verdict


def retract(
    outcome: readiness.Outcome, *, attestations: Sequence[attesting.Attestation]
) -> tuple[readiness.Outcome, tuple[Withheld, ...]]:
    imported = {
        item.check for item in attestations if item.kind is ledger.EntryKind.IMPORTED
    }
    stated: dict[str, verdicts.Verdict] = {}
    withheld: list[Withheld] = []
    for name, verdict in outcome.verdicts.items():
        if name in imported and verdict.permits_installation:
            withheld.append(Withheld(check=name, stated=verdict))
            stated[name] = verdicts.NotTested(WITHHELD_REASON)
            continue
        stated[name] = verdict

    counts: dict[str, int] = {}
    for verdict in stated.values():
        counts[verdict.stored_name] = counts.get(verdict.stored_name, 0) + 1

    narrowed = readiness.Outcome(
        ready=outcome.ready and verdicts.require_all(stated.values()),
        verdicts=stated,
        counts=counts,
        faults=outcome.faults,
    )
    return narrowed, tuple(withheld)

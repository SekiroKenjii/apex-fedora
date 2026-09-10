"""Decide whether a candidate may be installed.

The decision is a conjunction over the whole catalogue, never a fold. `meet` has not tested
as its identity, so folding 62 checks where 38 were never run would report the verdict of the
24 that were, and retracting a blocked result would raise a group to passing.

Nothing here reads a file. Resolving proofs, replaying a chain and re-hashing bytes all
happen before the fold, so every decision can be tested exhaustively without a filesystem.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

from apex.kernel import claims, identifiers, refusals
from apex.kernel.verdicts import BLOCKED, PASSED, NotTested, Verdict, require_all


@dataclasses.dataclass(frozen=True, slots=True)
class ResolvedRecord:
    """One stored result, with its proofs already resolved and re-hashed."""

    check: identifiers.CheckId
    verdict: Verdict
    environment: claims.EnvironmentKind
    candidate: identifiers.Digest
    proofs_intact: bool
    proof_count: int
    imported: bool


@dataclasses.dataclass(frozen=True, slots=True)
class Outcome:
    ready: bool
    verdicts: Mapping[str, Verdict]
    counts: Mapping[str, int]
    faults: tuple[str, ...]

    def verdict_of(self, check: str) -> Verdict:
        return self.verdicts[check]


def _blocked(
    reason: refusals.RefusalReason, check: identifiers.CheckId, detail: str
) -> str:
    return f"{reason.value}: {check} {detail}"


def _judge(
    record: ResolvedRecord,
    *,
    required_environment: claims.EnvironmentKind,
    candidate: identifiers.Digest,
) -> tuple[Verdict, str | None]:
    """A detected fault becomes Blocked. It must never look like a check nobody ran."""
    if record.candidate != candidate:
        return BLOCKED, _blocked(
            refusals.RefusalReason.RECORD_NOT_BOUND_TO_CANDIDATE,
            record.check,
            "cites another build",
        )
    if not record.proofs_intact:
        return BLOCKED, _blocked(
            refusals.RefusalReason.PROOF_ALTERED,
            record.check,
            "has a proof that no longer matches",
        )
    if not record.environment.satisfies(required_environment):
        return BLOCKED, _blocked(
            refusals.RefusalReason.HARDWARE_REQUIRES_PHYSICAL,
            record.check,
            f"was recorded in {record.environment}, not {required_environment}",
        )
    if record.verdict == PASSED and record.proof_count == 0:
        return BLOCKED, _blocked(
            refusals.RefusalReason.PASS_REQUIRES_PROOF, record.check, "passed without proof"
        )
    return record.verdict, None


def evaluate(
    *,
    required: Mapping[str, claims.EnvironmentKind],
    records: Sequence[ResolvedRecord],
    candidate: identifiers.Digest | None,
) -> Outcome:
    faults: list[str] = []
    seen: dict[str, ResolvedRecord] = {}
    for record in records:
        name = str(record.check)
        if name not in required:
            faults.append(
                _blocked(
                    refusals.RefusalReason.UNKNOWN_CHECK,
                    record.check,
                    "is not in the catalogue",
                )
            )
            continue
        if name in seen:
            faults.append(
                _blocked(
                    refusals.RefusalReason.DUPLICATE_EVIDENCE, record.check, "has two records"
                )
            )
            continue
        seen[name] = record

    stated: dict[str, Verdict] = {}
    standing_on_imported = False
    for name, environment in required.items():
        found = seen.get(name)
        if found is None:
            stated[name] = NotTested(refusals.RefusalReason.NO_VERIFIED_RESULT)
            continue
        verdict, fault = _judge(
            found,
            required_environment=environment,
            candidate=candidate or found.candidate,
        )
        stated[name] = verdict
        if fault is not None:
            faults.append(fault)
        if found.imported and verdict.permits_installation:
            standing_on_imported = True

    counts: dict[str, int] = {}
    for verdict in stated.values():
        counts[verdict.stored_name] = counts.get(verdict.stored_name, 0) + 1

    ready = (
        candidate is not None
        and not faults
        and not standing_on_imported
        and require_all(stated.values())
    )
    return Outcome(ready=ready, verdicts=stated, counts=counts, faults=tuple(faults))

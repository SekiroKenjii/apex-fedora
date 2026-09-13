"""Decide whether a candidate may be installed.

The decision is a conjunction over the whole catalogue, never a fold. `meet` has not tested
as its identity, so folding 62 checks where 38 were never run would report the verdict of the
24 that were, and retracting a blocked result would raise a group to passing.

Nothing here reads a file. Resolving proofs, replaying a chain and re-hashing bytes all
happen before the fold, so every decision can be tested exhaustively without a filesystem.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence

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


@dataclasses.dataclass(frozen=True, slots=True)
class _Stated:
    verdicts: dict[str, Verdict]
    faults: tuple[str, ...]
    standing_on_imported: bool


def _blocked(reason: refusals.RefusalReason, check: identifiers.CheckId, detail: str) -> str:
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
            refusals.RefusalReason.PROOF_ALTERED, record.check, "has a proof that no longer matches"
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


def _one_record_per_known_check(
    records: Sequence[ResolvedRecord], *, required: Mapping[str, claims.EnvironmentKind]
) -> tuple[dict[str, ResolvedRecord], tuple[str, ...]]:
    faults: list[str] = []
    seen: dict[str, ResolvedRecord] = {}
    for record in records:
        name = str(record.check)
        if name not in required:
            faults.append(
                _blocked(
                    refusals.RefusalReason.UNKNOWN_CHECK, record.check, "is not in the catalogue"
                )
            )
        elif name in seen:
            faults.append(
                _blocked(refusals.RefusalReason.DUPLICATE_EVIDENCE, record.check, "has two records")
            )
        else:
            seen[name] = record
    return seen, tuple(faults)


def _state_every_check(
    required: Mapping[str, claims.EnvironmentKind],
    seen: Mapping[str, ResolvedRecord],
    *,
    candidate: identifiers.Digest | None,
) -> _Stated:
    stated: dict[str, Verdict] = {}
    faults: list[str] = []
    standing_on_imported = False
    for name, environment in required.items():
        found = seen.get(name)
        if found is None:
            stated[name] = NotTested(refusals.RefusalReason.NO_VERIFIED_RESULT)
            continue
        verdict, fault = _judge(
            found, required_environment=environment, candidate=candidate or found.candidate
        )
        stated[name] = verdict
        if fault is not None:
            faults.append(fault)
        if found.imported and verdict.permits_installation:
            standing_on_imported = True
    return _Stated(verdicts=stated, faults=tuple(faults), standing_on_imported=standing_on_imported)


def _counts(verdicts: Iterable[Verdict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for verdict in verdicts:
        counts[verdict.stored_name] = counts.get(verdict.stored_name, 0) + 1
    return counts


def evaluate(
    *,
    required: Mapping[str, claims.EnvironmentKind],
    records: Sequence[ResolvedRecord],
    candidate: identifiers.Digest | None,
) -> Outcome:
    seen, reading_faults = _one_record_per_known_check(records, required=required)
    stated = _state_every_check(required, seen, candidate=candidate)
    faults = reading_faults + stated.faults
    ready = (
        candidate is not None
        and not faults
        and not stated.standing_on_imported
        and require_all(stated.verdicts.values())
    )
    return Outcome(
        ready=ready,
        verdicts=stated.verdicts,
        counts=_counts(stated.verdicts.values()),
        faults=faults,
    )

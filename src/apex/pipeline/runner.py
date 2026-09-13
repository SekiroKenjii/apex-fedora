"""Preflight the whole plan, apply in derived order, unwind on every terminal path.

Refusing before the first effect is a stronger guarantee than unwinding cleanly afterwards:
a run that was going to refuse never took a lock, opened a session or started a machine.
"""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import Mapping
from typing import Any

from apex.kernel import errors, identifiers, refusals
from apex.pipeline import plans, stages
from apex.pipeline.facts import FactKey, FactMap
from apex.ports import portset

SEED = identifiers.StageId("seed")


@dataclasses.dataclass(frozen=True, slots=True)
class Outcome:
    succeeded: bool
    facts: FactMap
    not_tested: tuple[identifiers.CheckId, ...]
    attested: tuple[identifiers.CheckId, ...]
    refusal: refusals.RefusalReason | None = None
    detail: str = ""


@dataclasses.dataclass(slots=True)
class _Progress[P]:
    """What one run has done so far. Mutable on purpose: it is the run's only ledger."""

    context: stages.RunContext[P]
    finalisers: list[stages.Finaliser] = dataclasses.field(default_factory=list)
    completed: set[str] = dataclasses.field(default_factory=set)
    attested: set[identifiers.CheckId] = dataclasses.field(default_factory=set)

    def attested_so_far(self) -> tuple[identifiers.CheckId, ...]:
        return tuple(sorted(self.attested, key=str))


def _unreached[P](plan: plans.Plan[P], completed: set[str]) -> tuple[identifiers.CheckId, ...]:
    pending: set[identifiers.CheckId] = set()
    for stage in plan.stages:
        if str(stage.id) not in completed:
            pending.update(stage.attests)
    return tuple(sorted(pending, key=str))


def run[P: portset.PortBundle](
    plan: plans.Plan[P], *, ports: P, seeds: Mapping[FactKey[Any], object] | None = None
) -> Outcome:
    """Seeds are the facts the caller already holds, credited to a stage named `seed`."""
    given = _seeded(seeds or {})
    verdicts = _preflight(plan, planning=ports.for_planning(), given=given)
    refused = _first_refusal(plan, verdicts, given=given)
    if refused is not None:
        return refused
    return _apply(plan, verdicts, ports=ports, given=given)


def _seeded(seeds: Mapping[FactKey[Any], object]) -> FactMap:
    facts = FactMap()
    for key, value in seeds.items():
        facts = facts.with_fact(key, value, produced_by=SEED)
    return facts


def _preflight[P](plan: plans.Plan[P], *, planning: P, given: FactMap) -> list[stages.Preflight]:
    context = stages.RunContext(facts=given, ports=planning)
    verdicts: list[stages.Preflight] = []
    for stage in plan.stages:
        try:
            verdicts.append(stage.preflight(context))
        except errors.InternalDefect as defect:
            raise errors.InternalDefect(f"{stage.id} acted during preflight: {defect}") from defect
    return verdicts


def _first_refusal[P](
    plan: plans.Plan[P], verdicts: list[stages.Preflight], *, given: FactMap
) -> Outcome | None:
    for stage, verdict in zip(plan.stages, verdicts, strict=True):
        if isinstance(verdict, stages.RefuseBecause):
            return Outcome(
                succeeded=False,
                facts=given,
                not_tested=_unreached(plan, set()),
                attested=(),
                refusal=verdict.reason,
                detail=f"{stage.id}: {verdict.detail}",
            )
    return None


def _apply[P](
    plan: plans.Plan[P], verdicts: list[stages.Preflight], *, ports: P, given: FactMap
) -> Outcome:
    progress = _Progress(context=stages.RunContext(facts=given, ports=ports))
    stopped: Outcome | None = None
    try:
        for stage, verdict in zip(plan.stages, verdicts, strict=True):
            if isinstance(verdict, stages.SkipBecause):
                continue
            stopped = _step(plan, stage, progress)
            if stopped is not None:
                break
    finally:
        _unwind(progress.finalisers)
    if stopped is not None:
        return stopped
    return Outcome(
        succeeded=True,
        facts=progress.context.facts,
        not_tested=_unreached(plan, progress.completed),
        attested=progress.attested_so_far(),
    )


def _step[P](plan: plans.Plan[P], stage: stages.Stage[P], progress: _Progress[P]) -> Outcome | None:
    result = stage.apply(progress.context)
    if isinstance(result, stages.Advance):
        progress.context = progress.context.with_facts(result.facts, by=stage.id)
        if result.finaliser is not None:
            progress.finalisers.append(result.finaliser)
        progress.completed.add(str(stage.id))
        progress.attested.update(stage.attests)
        return None
    if isinstance(result, stages.Skip):
        return None
    if isinstance(result, stages.Refuse):
        reason, detail = result.reason, result.detail
    else:
        reason, detail = refusals.RefusalReason.STAGE_FAILED, result.cause
    return Outcome(
        succeeded=False,
        facts=progress.context.facts,
        not_tested=_unreached(plan, progress.completed),
        attested=progress.attested_so_far(),
        refusal=reason,
        detail=f"{stage.id}: {detail}",
    )


def _unwind(finalisers: list[stages.Finaliser]) -> None:
    for finaliser in reversed(finalisers):
        with contextlib.suppress(Exception):
            finaliser.release()

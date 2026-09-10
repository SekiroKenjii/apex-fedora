"""Preflight the whole plan, apply in derived order, unwind on every terminal path.

Refusing before the first effect is a stronger guarantee than unwinding cleanly afterwards:
a run that was going to refuse never took a lock, opened a session or started a machine.
"""

from __future__ import annotations

import contextlib
import dataclasses
from typing import Any

from apex.kernel import errors, identifiers, refusals
from apex.pipeline import plans, stages
from apex.pipeline.facts import FactMap
from apex.registry import discovery


@dataclasses.dataclass(frozen=True, slots=True)
class Outcome:
    succeeded: bool
    facts: FactMap
    not_tested: tuple[identifiers.CheckId, ...]
    attested: tuple[identifiers.CheckId, ...]
    refusal: refusals.RefusalReason | None = None
    detail: str = ""


def _unreached(plan: plans.Plan, completed: set[str]) -> tuple[identifiers.CheckId, ...]:
    pending: set[identifiers.CheckId] = set()
    for stage in plan.stages:
        if str(stage.id) not in completed:
            pending.update(stage.attests)
    return tuple(sorted(pending, key=str))


def planning_ports() -> discovery.RefusingPorts:
    """During planning a stage may compute, never act."""
    return discovery.RefusingPorts()


def run(plan: plans.Plan, *, ports: Any = None) -> Outcome:
    planning = stages.RunContext(facts=FactMap(), ports=planning_ports())
    verdicts = []
    for stage in plan.stages:
        try:
            verdicts.append(stage.preflight(planning))
        except errors.InternalDefect as defect:
            raise errors.InternalDefect(
                f"{stage.id} acted during preflight: {defect}"
            ) from defect
    context = stages.RunContext(facts=FactMap(), ports=ports)
    for stage, verdict in zip(plan.stages, verdicts, strict=True):
        if isinstance(verdict, stages.RefuseBecause):
            return Outcome(
                succeeded=False,
                facts=context.facts,
                not_tested=_unreached(plan, set()),
                attested=(),
                refusal=verdict.reason,
                detail=f"{stage.id}: {verdict.detail}",
            )

    finalisers: list[stages.Finaliser] = []
    completed: set[str] = set()
    attested: set[identifiers.CheckId] = set()
    outcome: Outcome | None = None
    try:
        for stage, verdict in zip(plan.stages, verdicts, strict=True):
            if isinstance(verdict, stages.SkipBecause):
                continue
            result = stage.apply(context)
            if isinstance(result, stages.Advance):
                context = context.with_facts(result.facts, by=stage.id)
                if result.finaliser is not None:
                    finalisers.append(result.finaliser)
                completed.add(str(stage.id))
                attested.update(stage.attests)
                continue
            if isinstance(result, stages.Skip):
                continue
            if isinstance(result, stages.Refuse):
                reason, detail = result.reason, result.detail
            else:
                reason, detail = refusals.RefusalReason.STAGE_FAILED, result.cause
            outcome = Outcome(
                succeeded=False,
                facts=context.facts,
                not_tested=_unreached(plan, completed),
                attested=tuple(sorted(attested, key=str)),
                refusal=reason,
                detail=f"{stage.id}: {detail}",
            )
            break
    finally:
        for finaliser in reversed(finalisers):
            with contextlib.suppress(Exception):
                finaliser.release()

    if outcome is not None:
        return outcome
    return Outcome(
        succeeded=True,
        facts=context.facts,
        not_tested=_unreached(plan, completed),
        attested=tuple(sorted(attested, key=str)),
    )

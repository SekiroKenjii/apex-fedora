"""Keep a guest's report under the run's exports when no check is minted from it.

A fault that no catalogue check names still leaves what it found, the report and the
verdict the host drew from it; a probe leaves its observation as the guest gave it, for the
reader who records the check by hand with it as proof. Both are written beside the run's
other exports as the older tool kept its results files. Nothing here reaches the store.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import encoding, identifiers
from apex.pipeline import effects, facts, stages
from apex.ports import portset
from apex.verification import faulting, judging, probing, verifykeys

REPORT_SUFFIX = ".json"
Rendering = Callable[[Any], encoding.Document]


def for_case(case: faulting.FaultCase) -> stages.SimpleStage[portset.HostPorts]:
    """The fault's observations with the verdict written into them."""
    return _retaining(
        case.unit, verifykeys.fault_report(case), verifykeys.retained(case),
        lambda found: {**found.observations, judging.VERDICT: found.verdict.stored_name},
    )


def for_probe(case: probing.ProbeCase) -> stages.SimpleStage[portset.HostPorts]:
    """The probe's observations as the guest gave them, with no verdict at all."""
    return _retaining(
        case.unit, verifykeys.observed(case), verifykeys.retained_observation(case),
        lambda found: dict(found.observations),
    )


def _retaining(
    unit: identifiers.ProbeId,
    report: facts.FactKey[Any],
    key: facts.FactKey[Any],
    rendering: Rendering,
) -> stages.SimpleStage[portset.HostPorts]:
    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        target = exports.inside(
            context.facts[composition_keys.RUNTIME_ROOT],
            context.facts[composition_keys.RUN_ID],
            f"{unit}{REPORT_SUFFIX}",
        )
        document = rendering(context.facts[report])
        context.ports.files.write_atomic(
            target, encoding.canonical(document) + b"\n", mode=defaults.RECORD_MODE
        )
        return stages.Advance(facts={key: target})

    return stages.SimpleStage(
        id=identifiers.StageId(f"retain.{unit}"),
        reads=(report, composition_keys.RUNTIME_ROOT, composition_keys.RUN_ID),
        writes=(key,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.WRITES_RUNTIME}),
        preflight=stages.always_ready,
        apply=apply,
    )

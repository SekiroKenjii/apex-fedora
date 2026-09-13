"""Keep a fault's report under the run's exports when no check is minted from it.

A fault that no catalogue check names still leaves what it found: the report and the
verdict the host drew from it, written beside the run's other exports as the older tool
kept its results file. Nothing here reaches the evidence store.
"""

from __future__ import annotations

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import encoding, identifiers
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.verification import faulting, judging, verifykeys

REPORT_SUFFIX = ".json"


def for_case(case: faulting.FaultCase) -> stages.SimpleStage[portset.HostPorts]:
    key = verifykeys.retained(case)
    report = verifykeys.fault_report(case)

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        found = context.facts[report]
        target = exports.inside(
            context.facts[composition_keys.RUNTIME_ROOT],
            context.facts[composition_keys.RUN_ID],
            f"{case.unit}{REPORT_SUFFIX}",
        )
        document: encoding.Document = {
            **found.observations, judging.VERDICT: found.verdict.stored_name,
        }
        context.ports.files.write_atomic(
            target, encoding.canonical(document) + b"\n", mode=defaults.RECORD_MODE
        )
        return stages.Advance(facts={key: target})

    return stages.SimpleStage(
        id=identifiers.StageId(f"retain.{case.unit}"),
        reads=(report, composition_keys.RUNTIME_ROOT, composition_keys.RUN_ID),
        writes=(key,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.WRITES_RUNTIME}),
        preflight=stages.always_ready,
        apply=apply,
    )

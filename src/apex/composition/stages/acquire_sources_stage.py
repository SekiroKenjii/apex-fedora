"""Bring every locked source into the runtime root, checked against its pin."""

from __future__ import annotations

from apex.composition import keys
from apex.kernel import errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.trust import acquiring


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    try:
        acquired = acquiring.acquire(
            context.ports,
            reviewed=context.facts[keys.REVIEWED_LOCK],
            root=context.facts[keys.RUNTIME_ROOT],
        )
    except errors.Refusal as refusal:
        return stages.Refuse(refusal.reason, detail=refusal.subject)
    return stages.Advance(facts={keys.SOURCES: acquired})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("sources.acquire"),
    reads=(keys.REVIEWED_LOCK, keys.RUNTIME_ROOT, keys.BUILDER_VERIFIED),
    writes=(keys.SOURCES,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.NETWORK_FETCH, effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)

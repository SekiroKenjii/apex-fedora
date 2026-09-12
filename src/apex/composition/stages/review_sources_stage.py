"""Read the reviewed source lock before anything is fetched or sent."""

from __future__ import annotations

from apex.composition import keys
from apex.config import sourcepins
from apex.kernel import errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import portset


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    try:
        reviewed = sourcepins.load(context.facts[keys.REPOSITORY])
    except errors.Refusal as refusal:
        return stages.Refuse(refusal.reason, detail=refusal.subject)
    return stages.Advance(facts={keys.REVIEWED_LOCK: reviewed})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("sources.review"),
    reads=(keys.REPOSITORY,),
    writes=(keys.REVIEWED_LOCK,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.READS_HOST}),
    preflight=stages.always_ready,
    apply=apply,
)

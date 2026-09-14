"""Prove every input of the medium on the host and write the request, before the builder."""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.kernel import errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.verification import ventoymedia, verifykeys


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    try:
        prepared = ventoymedia.prepare(
            context.ports,
            context.facts[composition_keys.RUNTIME_ROOT],
            context.facts[composition_keys.RUN_ID],
            context.facts[composition_keys.REPOSITORY],
            context.facts[verifykeys.VENTOY_INPUTS],
        )
    except errors.Refusal as refusal:
        return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
    except errors.PortFailure as failure:
        return stages.Fail(cause=failure.cause)
    return stages.Advance(facts={verifykeys.VENTOY_PREPARED: prepared})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("ventoy.inputs"),
    reads=(
        composition_keys.RUNTIME_ROOT,
        composition_keys.RUN_ID,
        composition_keys.REPOSITORY,
        verifykeys.VENTOY_INPUTS,
    ),
    writes=(verifykeys.VENTOY_PREPARED,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.NETWORK_FETCH, effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)

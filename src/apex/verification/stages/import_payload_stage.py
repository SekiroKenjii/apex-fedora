"""Ask the builder to import the parent build's archive into its store before the fault."""

from __future__ import annotations

from apex.composition import agentrun
from apex.kernel import errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.verification import verifykeys

UNIT = identifiers.ProbeId("build.import-payload")


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    try:
        reply = agentrun.run_unit(
            context.ports,
            context.facts[verifykeys.GUEST],
            context.facts[verifykeys.AGENT],
            unit=UNIT,
            arguments={
                "work": str(context.facts[verifykeys.WORK]),
                "parent": str(context.facts[verifykeys.PARENT]),
            },
            token=context.ports.identities.token(),
        )
    except errors.Refusal as refusal:
        return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
    except errors.PortFailure as failure:
        return stages.Fail(cause=failure.cause)
    return stages.Advance(facts={verifykeys.IMPORTED: reply.observations})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("payload.import"),
    reads=(verifykeys.GUEST, verifykeys.AGENT, verifykeys.WORK, verifykeys.PARENT),
    writes=(verifykeys.IMPORTED,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC, effects.Effect.MUTATES_GUEST}),
    preflight=stages.always_ready,
    apply=apply,
)

"""Ask the builder to stand the fixture's stored image A in as the payload of this run."""

from __future__ import annotations

from apex.composition import agentrun
from apex.composition import keys as composition_keys
from apex.kernel import errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.provisioning.fixtures import update_fixture
from apex.verification import verifykeys

UNIT = identifiers.ProbeId("build.tag-payload")


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    located = context.facts[verifykeys.FIXTURE]
    try:
        reply = agentrun.run_unit(
            context.ports,
            context.facts[verifykeys.GUEST],
            context.facts[verifykeys.AGENT],
            unit=UNIT,
            arguments={
                "work": str(context.facts[composition_keys.REMOTE]),
                "source": update_fixture.image_tag(located.report.run, "a"),
                "digest": str(located.image_a.digest),
            },
            token=context.ports.identities.token(),
        )
    except errors.Refusal as refusal:
        return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
    except errors.PortFailure as failure:
        return stages.Fail(cause=failure.cause)
    return stages.Advance(facts={verifykeys.TAGGED: reply.observations})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("payload.tag"),
    reads=(
        verifykeys.GUEST, verifykeys.AGENT, verifykeys.FIXTURE, composition_keys.REMOTE,
        composition_keys.TRANSFERRED,
    ),
    writes=(verifykeys.TAGGED,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC, effects.Effect.MUTATES_GUEST}),
    preflight=stages.always_ready,
    apply=apply,
)

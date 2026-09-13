"""Ask the guest for one observation and hold it unjudged, for a reader to judge later."""

from __future__ import annotations

from apex.kernel import errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.verification import probing, verifykeys


def for_case(case: probing.ProbeCase) -> stages.SimpleStage[portset.HostPorts]:
    key = verifykeys.observed(case)

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        ports = context.ports
        try:
            found = probing.observe(
                ports, context.facts[verifykeys.GUEST], context.facts[verifykeys.AGENT], case,
                token=ports.identities.token(),
            )
        except errors.Refusal as refusal:
            return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
        except errors.PortFailure as failure:
            return stages.Fail(cause=failure.cause)
        return stages.Advance(facts={key: found})

    return stages.SimpleStage(
        id=identifiers.StageId(str(case.unit)),
        reads=(verifykeys.GUEST, verifykeys.AGENT),
        writes=(key,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.REMOTE_EXEC}),
        preflight=stages.always_ready,
        apply=apply,
    )

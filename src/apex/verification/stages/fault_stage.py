"""Ask the guest to attempt one fault and hold what it reported.

One stage per case, made here rather than declared, because a fault stage's shape is the same
for every case and only the unit it asks for differs. The guest's refusal is this stage's
refusal, with the guest's words.
"""

from __future__ import annotations

from apex.composition import agentrun
from apex.kernel import errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.verification import faulting, verifykeys


def for_case(case: faulting.FaultCase) -> stages.SimpleStage[portset.HostPorts]:
    key = verifykeys.fault_report(case)

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        try:
            reply = agentrun.run_unit(
                context.ports,
                context.facts[verifykeys.GUEST],
                context.facts[verifykeys.AGENT],
                unit=case.unit,
                arguments=case.arguments,
                token=context.ports.identities.token(),
            )
        except errors.Refusal as refusal:
            return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
        except errors.PortFailure as failure:
            return stages.Fail(cause=failure.cause)
        found = faulting.report(case, reply.observations, reply=reply.document())
        return stages.Advance(facts={key: found})

    return stages.SimpleStage(
        id=identifiers.StageId(str(case.unit)),
        reads=(verifykeys.GUEST, verifykeys.AGENT),
        writes=(key,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.REMOTE_EXEC, effects.Effect.MUTATES_GUEST}),
        preflight=stages.always_ready,
        apply=apply,
    )


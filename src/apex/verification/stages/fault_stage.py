"""Ask the guest to attempt one fault and hold what it reported.

One stage per case, made here rather than declared, because a fault stage's shape is the same
for every case and only the unit it asks for differs. The guest's refusal is this stage's
refusal, with the guest's words. A case whose arguments are only known in the run, such as
the work directory the host laid out, is given a reading of them from the run's facts.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from apex.composition import agentrun
from apex.kernel import encoding, errors, identifiers
from apex.pipeline import effects, facts, stages
from apex.ports import portset
from apex.verification import faulting, verifykeys

Arguments = Callable[[stages.RunContext[portset.HostPorts]], Mapping[str, encoding.JsonValue]]


def for_case(
    case: faulting.FaultCase,
    *,
    arguments: Arguments | None = None,
    after: Sequence[facts.FactKey[Any]] = (),
) -> stages.SimpleStage[portset.HostPorts]:
    key = verifykeys.fault_report(case)

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        asked = (
            case
            if arguments is None
            else dataclasses.replace(case, arguments=dict(arguments(context)))
        )
        try:
            reply = agentrun.run_unit(
                context.ports,
                context.facts[verifykeys.GUEST],
                context.facts[verifykeys.AGENT],
                unit=asked.unit,
                arguments=asked.arguments,
                token=context.ports.identities.token(),
            )
        except errors.Refusal as refusal:
            return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
        except errors.PortFailure as failure:
            return stages.Fail(cause=failure.cause)
        found = faulting.report(asked, reply.observations, reply=reply.document())
        return stages.Advance(facts={key: found})

    return stages.SimpleStage(
        id=identifiers.StageId(str(case.unit)),
        reads=(verifykeys.GUEST, verifykeys.AGENT, *after),
        writes=(key,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.REMOTE_EXEC, effects.Effect.MUTATES_GUEST}),
        preflight=stages.always_ready,
        apply=apply,
    )

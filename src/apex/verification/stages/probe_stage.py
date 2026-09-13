"""Ask the guest for one observation and hold it unjudged, for a reader to judge later.

A case whose arguments are only known in the run, such as the directories the host laid
out for it, is given a reading of them from the run's facts, as a fault case is.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from apex.kernel import encoding, errors, identifiers
from apex.pipeline import effects, facts, stages
from apex.ports import portset
from apex.verification import probing, verifykeys

Arguments = Callable[[stages.RunContext[portset.HostPorts]], Mapping[str, encoding.JsonValue]]


def for_case(
    case: probing.ProbeCase,
    *,
    arguments: Arguments | None = None,
    after: Sequence[facts.FactKey[Any]] = (),
) -> stages.SimpleStage[portset.HostPorts]:
    key = verifykeys.observed(case)

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        ports = context.ports
        asked = (
            case
            if arguments is None
            else dataclasses.replace(case, arguments=dict(arguments(context)))
        )
        try:
            found = probing.observe(
                ports,
                context.facts[verifykeys.GUEST],
                context.facts[verifykeys.AGENT],
                asked,
                token=ports.identities.token(),
            )
        except errors.Refusal as refusal:
            return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
        except errors.PortFailure as failure:
            return stages.Fail(cause=failure.cause)
        return stages.Advance(facts={key: found})

    return stages.SimpleStage(
        id=identifiers.StageId(str(case.unit)),
        reads=(verifykeys.GUEST, verifykeys.AGENT, *after),
        writes=(key,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.REMOTE_EXEC}),
        preflight=stages.always_ready,
        apply=apply,
    )

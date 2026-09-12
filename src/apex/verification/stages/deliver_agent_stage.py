"""Put the guest program into the guest under this run's directory."""

from __future__ import annotations

from apex.composition import agentrun, exports
from apex.composition import keys as composition_keys
from apex.kernel import errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.verification import verifykeys


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    remote = exports.remote(context.facts[composition_keys.RUN_ID])
    try:
        install = agentrun.deliver(
            context.ports,
            context.facts[verifykeys.GUEST],
            wheel=context.facts[verifykeys.WHEEL],
            remote=remote,
        )
    except errors.PortFailure as failure:
        return stages.Fail(cause=failure.cause)
    return stages.Advance(facts={verifykeys.AGENT: install})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("agent.deliver"),
    reads=(composition_keys.RUN_ID, verifykeys.GUEST, verifykeys.WHEEL),
    writes=(verifykeys.AGENT,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)

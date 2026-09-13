"""Bring the pinned upstream fingerprint tests into the runtime root, checked against the lock.

The guest never downloads, so the files the harness imports are fetched here, after the
builder has proved itself and before anything is sent to it.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.config import fingerprintpins
from apex.kernel import errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.trust import testsources
from apex.verification import verifykeys


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    try:
        reviewed = fingerprintpins.load(context.facts[composition_keys.REPOSITORY])
        acquired = testsources.acquire(
            context.ports, reviewed=reviewed, root=context.facts[composition_keys.RUNTIME_ROOT]
        )
    except errors.Refusal as refusal:
        return stages.Refuse(refusal.reason, detail=refusal.subject)
    except errors.PortFailure as failure:
        return stages.Fail(cause=failure.cause)
    return stages.Advance(facts={verifykeys.TEST_SOURCES: acquired})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("fingerprint.acquire"),
    reads=(composition_keys.REPOSITORY, composition_keys.RUNTIME_ROOT, verifykeys.GUEST),
    writes=(verifykeys.TEST_SOURCES,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.NETWORK_FETCH, effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)

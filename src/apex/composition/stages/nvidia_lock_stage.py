"""Read the reviewed NVIDIA lock and refuse a parent image its compiler does not match."""

from __future__ import annotations

from apex.composition import keys, nvidialock
from apex.kernel import errors, identifiers, refusals
from apex.pipeline import stages
from apex.ports import portset


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    parent = context.facts[keys.PARENT]
    if parent is None:
        return stages.Refuse(
            reason=refusals.RefusalReason.BUILD_PARENT_REQUIRED,
            detail="the NVIDIA packages are built for one completed image",
        )
    try:
        lock = nvidialock.load(context.ports, context.facts[keys.REPOSITORY])
        nvidialock.require_compiler(context.ports, context.facts[keys.RUNTIME_ROOT], parent, lock)
    except errors.Refusal as refusal:
        return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
    return stages.Advance(facts={keys.NVIDIA_LOCK: lock})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("nvidia.lock"),
    reads=(keys.PARENT, keys.FROZEN, keys.REPOSITORY, keys.RUNTIME_ROOT),
    writes=(keys.NVIDIA_LOCK,),
    attests=frozenset(),
    effects=frozenset(),
    preflight=stages.always_ready,
    apply=apply,
)

"""Give a private QCOW2 fixture its disposable account, or refuse the request for anything else.

The account goes only into a QCOW2 the operator marked for testing, never into an image,
an installer or a live medium, and the refusal is made in preflight so a build that could
not carry it never opens a session. The blueprint reaches the guest by name beside the
sources, where the disk script looks for it.
"""

from __future__ import annotations

from apex.composition import accessgrant, keys
from apex.config import defaults
from apex.kernel import errors, identifiers, refusals
from apex.model import builds
from apex.pipeline import effects, stages
from apex.ports import portset


def preflight(context: stages.RunContext[portset.HostPorts]) -> stages.Preflight:
    kind = context.facts[keys.KIND]
    if context.facts[keys.TEST_ACCESS] and kind is not builds.ArtifactKind.QCOW2:
        return stages.RefuseBecause(
            refusals.RefusalReason.TEST_ACCESS_NOT_QCOW2,
            detail=f"a {kind} carries no disposable account",
        )
    return stages.Ready()


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    if not context.facts[keys.TEST_ACCESS]:
        return stages.Advance(facts={keys.ACCESS: None})
    try:
        granted = accessgrant.grant(
            context.ports, root=context.facts[keys.RUNTIME_ROOT], run=context.facts[keys.RUN_ID]
        )
        context.ports.guest.send(
            context.facts[keys.BUILDER_VERIFIED],
            local=granted.blueprint,
            remote=context.facts[keys.REMOTE].joined(defaults.REMOTE_BLUEPRINT_NAME),
            deadline=defaults.TRANSFER_DEADLINE,
        )
    except errors.PortFailure as failure:
        return stages.Fail(cause=failure.cause)
    return stages.Advance(facts={keys.ACCESS: granted})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("access.grant"),
    reads=(
        keys.TEST_ACCESS,
        keys.KIND,
        keys.RUNTIME_ROOT,
        keys.RUN_ID,
        keys.BUILDER_VERIFIED,
        keys.REMOTE,
        keys.TRANSFERRED,
    ),
    writes=(keys.ACCESS,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.WRITES_RUNTIME, effects.Effect.REMOTE_EXEC}),
    preflight=preflight,
    apply=apply,
)

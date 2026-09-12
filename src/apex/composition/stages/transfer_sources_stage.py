"""Send the screened bundle, and for a derived artifact the frozen document, to the guest.

The guest never receives a host path to open; every file it needs is placed under its own
run directory by name.
"""

from __future__ import annotations

from apex.composition import exports, keys
from apex.config import defaults
from apex.kernel import errors, identifiers, safepaths
from apex.model import builds
from apex.pipeline import effects, stages
from apex.ports import portset


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    builder = context.facts[keys.BUILDER_VERIFIED]
    remote = context.facts[keys.REMOTE]
    root = context.facts[keys.RUNTIME_ROOT]
    run = context.facts[keys.RUN_ID]
    deliveries: list[tuple[safepaths.SafePath, safepaths.RemotePath]] = [
        (context.facts[keys.SOURCE_BUNDLE].archive, remote.joined(defaults.SOURCE_ARCHIVE_NAME))
    ]
    if context.facts[keys.FROZEN] is not None:
        document = exports.inside(root, run, builds.TARGET_DOCUMENT)
        deliveries.append((document, remote.joined(builds.TARGET_DOCUMENT)))
    placed = []
    for local, target in deliveries:
        try:
            context.ports.guest.send(
                builder, local=local, remote=target, deadline=defaults.TRANSFER_DEADLINE
            )
        except errors.PortFailure as failure:
            return stages.Fail(cause=str(failure))
        placed.append(target)
    return stages.Advance(facts={keys.TRANSFERRED: tuple(placed)})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("guest.transfer"),
    reads=(
        keys.BUILDER_VERIFIED, keys.REMOTE, keys.SOURCE_BUNDLE, keys.SOURCE_MANIFEST,
        keys.FROZEN, keys.RUNTIME_ROOT, keys.RUN_ID,
    ),
    writes=(keys.TRANSFERRED,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)

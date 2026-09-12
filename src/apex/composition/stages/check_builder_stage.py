"""The guest that will build must be the isolated builder and nothing else."""

from __future__ import annotations

from apex.composition import keys
from apex.config import defaults
from apex.kernel import commands, identifiers, refusals
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset

CHECK = guestshell.RemoteScript.of(
    guestshell.Step.of("test", "-f", defaults.BUILDER_MARKER),
    guestshell.Step.of("systemd-detect-virt", "--quiet", "--vm"),
)


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    builder = context.facts[keys.BUILDER]
    completed = context.ports.guest.run(
        builder,
        guestshell.GuestRun(
            script=CHECK,
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=commands.OutputLimit.default(),
        ),
    )
    if not completed.succeeded:
        return stages.Refuse(
            refusals.RefusalReason.BUILDER_NOT_ISOLATED,
            detail=f"the guest at port {builder.port} is not the isolated builder",
        )
    return stages.Advance(facts={keys.BUILDER_VERIFIED: builder})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("builder.check"),
    reads=(keys.BUILDER, keys.FROZEN),
    writes=(keys.BUILDER_VERIFIED,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)

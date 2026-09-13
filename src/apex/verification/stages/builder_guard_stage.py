"""The builder becomes the guest of a verification only after it proves it is the builder.

The same two conditions the build recipes check, the marker and the virtual machine, are
asked here before the agent is delivered or a fixture is made, so a verification never
runs its fault on a machine that merely answers at the builder's port.
"""

from __future__ import annotations

from apex.composition.stages import check_builder_stage
from apex.config import defaults
from apex.kernel import commands, identifiers, refusals
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset
from apex.verification import verifykeys


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    builder = context.facts[verifykeys.BUILDER]
    completed = context.ports.guest.run(
        builder,
        guestshell.GuestRun(
            script=check_builder_stage.CHECK,
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=commands.OutputLimit.default(),
        ),
    )
    if not completed.succeeded:
        return stages.Refuse(
            refusals.RefusalReason.BUILDER_NOT_ISOLATED,
            detail=f"the guest at port {builder.port} is not the isolated builder",
        )
    return stages.Advance(facts={verifykeys.GUEST: builder})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("builder.guard"),
    reads=(verifykeys.BUILDER,),
    writes=(verifykeys.GUEST,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)

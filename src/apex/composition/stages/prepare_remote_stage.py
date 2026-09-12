"""A private directory in the guest for this run alone."""

from __future__ import annotations

from apex.composition import exports, keys
from apex.config import defaults
from apex.kernel import commands, identifiers
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    remote = exports.remote(context.facts[keys.RUN_ID])
    completed = context.ports.guest.run(
        context.facts[keys.BUILDER_VERIFIED],
        guestshell.GuestRun(
            script=guestshell.RemoteScript.of(
                guestshell.Step.of("mkdir", "-m", defaults.REMOTE_DIRECTORY_MODE, str(remote))
            ),
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=commands.OutputLimit.default(),
        ),
    )
    if not completed.succeeded:
        return stages.Fail(cause=f"the guest could not create {remote}")
    return stages.Advance(facts={keys.REMOTE: remote})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("guest.prepare"),
    reads=(keys.BUILDER_VERIFIED, keys.RUN_ID, keys.SOURCES),
    writes=(keys.REMOTE,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)

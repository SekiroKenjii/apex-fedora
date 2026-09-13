"""A private work directory in the builder for the installer trust fault, named for its run."""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import commands, identifiers, safepaths
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset
from apex.verification import verifykeys


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    work = safepaths.RemotePath(
        f"{defaults.TRUST_WORK_PREFIX}{context.facts[composition_keys.RUN_ID]}"
    )
    made = context.ports.guest.run(
        context.facts[verifykeys.GUEST],
        guestshell.GuestRun(
            script=guestshell.RemoteScript.of(
                guestshell.Step.of("mkdir", "-m", defaults.REMOTE_DIRECTORY_MODE, str(work))
            ),
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=commands.OutputLimit.default(),
        ),
    )
    if not made.succeeded:
        return stages.Fail(cause=f"the guest could not create {work}")
    return stages.Advance(facts={verifykeys.WORK: work})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("trust.work"),
    reads=(verifykeys.GUEST, verifykeys.AGENT, composition_keys.RUN_ID),
    writes=(verifykeys.WORK,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)

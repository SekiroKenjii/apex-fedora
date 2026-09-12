"""Bring the guest's output home, whether or not the build succeeded.

A failed build's logs are evidence and are retrieved the same way. The ownership step is
tolerated when it fails, because output that already belongs to the builder account is the
common case and an absent directory is reported by the copy that follows.
"""

from __future__ import annotations

from apex.composition import exports, keys
from apex.config import defaults
from apex.kernel import commands, errors, identifiers
from apex.model import builds
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    builder = context.facts[keys.BUILDER_VERIFIED]
    remote = context.facts[keys.REMOTE]
    output = remote.joined(builds.OUTPUT_DIRECTORY)
    context.ports.guest.run(
        builder,
        guestshell.GuestRun(
            script=guestshell.RemoteScript.of(
                guestshell.Step(
                    commands.Argv.of("sudo", "chown", "-R", defaults.BUILDER_OWNER, str(output)),
                    quiet_errors=True,
                    tolerated=True,
                )
            ),
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=commands.OutputLimit.default(),
        ),
    )
    try:
        context.ports.guest.receive(
            builder,
            remote=output,
            into=exports.directory(context.facts[keys.RUNTIME_ROOT], context.facts[keys.RUN_ID]),
            recursive=True,
            deadline=defaults.TRANSFER_DEADLINE,
        )
    except errors.PortFailure:
        return stages.Advance(facts={keys.RETRIEVED: False})
    return stages.Advance(facts={keys.RETRIEVED: True})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("build.retrieve"),
    reads=(keys.BUILDER_VERIFIED, keys.REMOTE, keys.BUILD_RUN, keys.RUNTIME_ROOT, keys.RUN_ID),
    writes=(keys.RETRIEVED,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC, effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)

"""Lay the update fixture's work directory out in the builder, file by file.

The fixture unit reads the target document, the grub repair script and the reviewed retry
preset under a directory named for its run; the host sends each by name and nothing else.
"""

from __future__ import annotations

import posixpath

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import commands, errors, identifiers, safepaths
from apex.model import builds
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset
from apex.verification import verifykeys


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    root = context.facts[composition_keys.RUNTIME_ROOT]
    run = context.facts[composition_keys.RUN_ID]
    repository = context.facts[composition_keys.REPOSITORY]
    guest = context.facts[verifykeys.GUEST]
    work = safepaths.RemotePath(f"{defaults.UPDATE_WORK_PREFIX}{run}")
    deliveries = (
        (exports.inside(root, run, builds.TARGET_DOCUMENT), work.joined(builds.TARGET_DOCUMENT)),
        (
            safepaths.SafePath(repository.path / defaults.GRUB_REPAIR_PATH),
            work.joined(defaults.GRUB_REPAIR_PATH),
        ),
        (
            safepaths.SafePath(repository.path / defaults.RETRY_PRESET_PATH),
            work.joined(defaults.RETRY_PRESET_PATH),
        ),
    )
    directories = sorted({posixpath.dirname(str(target)) for _, target in deliveries})
    made = context.ports.guest.run(
        guest,
        guestshell.GuestRun(
            script=guestshell.RemoteScript.of(
                guestshell.Step.of(
                    "mkdir", "-p", "-m", defaults.REMOTE_DIRECTORY_MODE, str(work), *directories
                )
            ),
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=commands.OutputLimit.default(),
        ),
    )
    if not made.succeeded:
        return stages.Fail(cause=f"the guest could not create {work}")
    try:
        for local, target in deliveries:
            context.ports.guest.send(
                guest, local=local, remote=target, deadline=defaults.TRANSFER_DEADLINE
            )
    except errors.PortFailure as failure:
        return stages.Fail(cause=failure.cause)
    return stages.Advance(facts={verifykeys.WORK: work})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("update.work"),
    reads=(
        verifykeys.GUEST, verifykeys.AGENT, verifykeys.TARGET, composition_keys.REPOSITORY,
        composition_keys.RUNTIME_ROOT, composition_keys.RUN_ID,
    ),
    writes=(verifykeys.WORK,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)

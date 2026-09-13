"""Lay the fingerprint test's work directory out in the builder, file by file.

The older host packed the checkout and unpacked it in the builder; here only what the unit
reads is sent, each file by name under the work directory the unit expects: the pinned
upstream tests, the reviewed lock beside them, and the target document. The guest never
receives a host path to open.
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
from apex.trust import testsources
from apex.verification import verifykeys

LOCK = f"{defaults.FINGERPRINT_LOCK_DIRECTORY}/{defaults.FINGERPRINT_LOCK_NAME}"


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    root = context.facts[composition_keys.RUNTIME_ROOT]
    run = context.facts[composition_keys.RUN_ID]
    guest = context.facts[verifykeys.GUEST]
    work = safepaths.RemotePath(f"{defaults.FINGERPRINT_WORK_PREFIX}{run}")
    deliveries = [
        *(
            (testsources.sources_directory(root) / item.name,
             work.joined(f"{defaults.FINGERPRINT_SOURCES_NAME}/{item.name}"))
            for item in context.facts[verifykeys.TEST_SOURCES].files
        ),
        (testsources.lock_copy(root), work.joined(LOCK)),
        (exports.inside(root, run, builds.TARGET_DOCUMENT), work.joined(builds.TARGET_DOCUMENT)),
    ]
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
    id=identifiers.StageId("fingerprint.work"),
    reads=(
        verifykeys.GUEST, verifykeys.AGENT, verifykeys.TEST_SOURCES, verifykeys.TARGET,
        composition_keys.RUNTIME_ROOT, composition_keys.RUN_ID,
    ),
    writes=(verifykeys.WORK,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)

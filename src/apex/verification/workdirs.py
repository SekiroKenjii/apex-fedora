"""A work directory made in the guest and the run's files delivered into it, as one step."""

from __future__ import annotations

import posixpath
from collections.abc import Sequence

from apex.config import defaults
from apex.kernel import commands, errors, safepaths
from apex.pipeline import stages
from apex.ports import guestshell, portset
from apex.verification import verifykeys

Delivery = tuple[safepaths.SafePath, safepaths.RemotePath]


def deliver(
    context: stages.RunContext[portset.HostPorts],
    work: safepaths.RemotePath,
    deliveries: Sequence[Delivery],
) -> stages.StageResult:
    """Make the directory and every target's directory, then send each file; the work is a fact."""
    guest = context.facts[verifykeys.GUEST]
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

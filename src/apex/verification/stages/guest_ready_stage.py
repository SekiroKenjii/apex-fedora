"""Wait for the guest to answer over ssh with its system running, as the older host did.

A guest that was just rebooted takes a while to come back; every stage after this one
assumes the shell is there. The two programs are the ones the older tool asked, and the
same two answers are accepted: a QEMU virtual machine whose system is running or degraded.
"""

from __future__ import annotations

from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, refusals
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset
from apex.verification import verifykeys

CLOCK = "clock"
SCRIPT = guestshell.RemoteScript.of(
    guestshell.Step.of("systemd-detect-virt", "--vm"),
    guestshell.Step(commands.Argv.of("systemctl", "is-system-running"), tolerated=True),
)


def answer(ports: portset.HostPorts, target: guestshell.GuestTarget) -> list[str] | None:
    """The two answers, or nothing while the shell is not there to give them."""
    try:
        completed = ports.guest.run(
            target,
            guestshell.GuestRun(
                script=SCRIPT,
                deadline=defaults.PROBE_DEADLINE,
                limit=commands.OutputLimit.default(),
            ),
        )
    except errors.PortFailure:
        return None
    return completed.stdout.decode(errors="replace").split()


def ready(lines: list[str] | None) -> bool:
    return (
        lines is not None
        and len(lines) == 2
        and lines[0] in defaults.VIRTUALISERS
        and lines[1] in defaults.SYSTEM_STATES
    )


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    ports = context.ports
    target = context.facts[verifykeys.GUEST]
    seen: list[list[str] | None] = []

    def answered() -> bool:
        seen.append(answer(ports, target))
        return ready(seen[-1])

    try:
        waited = ports.clock.wait_until(answered, defaults.GUEST_READY)
    except errors.PortFailure as failure:
        if failure.port != CLOCK:
            return stages.Fail(cause=failure.cause)
        return stages.Refuse(
            reason=refusals.RefusalReason.GUEST_NOT_READY,
            detail=f"{failure.cause}; last answer {seen[-1]!r}",
        )
    found: encoding.Document = {
        "virtualiser": seen[-1][0] if seen[-1] else None,
        "system": seen[-1][1] if seen[-1] else None,
        "waited_seconds": waited.seconds,
        "attempts": len(seen),
    }
    return stages.Advance(facts={verifykeys.READY: found})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("guest.ready"),
    reads=(verifykeys.GUEST,),
    writes=(verifykeys.READY,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)

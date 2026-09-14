"""Lay the medium's work directory out in the builder: the request and the three inputs."""

from __future__ import annotations

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import commands, errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset
from apex.provisioning.fixtures import ventoy_fixture
from apex.verification import verifykeys


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    root = context.facts[composition_keys.RUNTIME_ROOT]
    run = context.facts[composition_keys.RUN_ID]
    guest = context.facts[verifykeys.GUEST]
    prepared = context.facts[verifykeys.VENTOY_PREPARED]
    work = exports.remote(run).joined(defaults.VENTOY_WORK_DIRECTORY)
    made = context.ports.guest.run(
        guest,
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
    deliveries = (
        (exports.inside(root, run, ventoy_fixture.REQUEST_NAME), ventoy_fixture.REQUEST_NAME),
        (prepared.archive, ventoy_fixture.ARCHIVE),
        (prepared.live, ventoy_fixture.ISOS[0]),
        (prepared.ubuntu, ventoy_fixture.ISOS[1]),
    )
    try:
        for local, name in deliveries:
            context.ports.guest.send(
                guest, local=local, remote=work.joined(name), deadline=defaults.TRANSFER_DEADLINE
            )
    except errors.PortFailure as failure:
        return stages.Fail(cause=failure.cause)
    return stages.Advance(facts={verifykeys.WORK: work})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("ventoy.work"),
    reads=(
        verifykeys.GUEST,
        verifykeys.AGENT,
        verifykeys.VENTOY_PREPARED,
        composition_keys.RUNTIME_ROOT,
        composition_keys.RUN_ID,
    ),
    writes=(verifykeys.WORK,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)

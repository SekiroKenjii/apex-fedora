"""Place the tested packages and the request beside the sources in the builder, by name."""

from __future__ import annotations

from apex.composition import exports, keys
from apex.config import defaults
from apex.kernel import commands, errors, identifiers, safepaths
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    builder = context.facts[keys.BUILDER_VERIFIED]
    remote = context.facts[keys.REMOTE]
    root = context.facts[keys.RUNTIME_ROOT]
    request = context.facts[keys.FINGERPRINT_REQUEST]
    inputs = remote.joined(defaults.FINGERPRINT_INPUTS_DIRECTORY)
    made = context.ports.guest.run(
        builder,
        guestshell.GuestRun(
            script=guestshell.RemoteScript.of(
                guestshell.Step.of("mkdir", "-m", defaults.REMOTE_DIRECTORY_MODE, str(inputs))
            ),
            deadline=defaults.GUEST_COMMAND_DEADLINE,
            limit=commands.OutputLimit.default(),
        ),
    )
    if not made.succeeded:
        return stages.Fail(cause=f"the guest could not create {inputs}")
    packages = exports.inside(
        root, request.rpm_build, f"{exports.OUTPUT}/{defaults.FINGERPRINT_PACKAGES_DIRECTORY}"
    )
    deliveries: list[tuple[safepaths.SafePath, safepaths.RemotePath]] = [
        (
            exports.inside(root, context.facts[keys.RUN_ID], defaults.FINGERPRINT_REQUEST_NAME),
            remote.joined(defaults.FINGERPRINT_REQUEST_NAME),
        ),
        *((packages / name, inputs.joined(name)) for name in request.rpms),
    ]
    placed = []
    try:
        for local, target in deliveries:
            context.ports.guest.send(
                builder, local=local, remote=target, deadline=defaults.TRANSFER_DEADLINE
            )
            placed.append(target)
    except errors.PortFailure as failure:
        return stages.Fail(cause=failure.cause)
    return stages.Advance(facts={keys.FINGERPRINT_DELIVERED: tuple(placed)})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("fingerprint.deliver"),
    reads=(
        keys.BUILDER_VERIFIED,
        keys.REMOTE,
        keys.TRANSFERRED,
        keys.FINGERPRINT_REQUEST,
        keys.RUNTIME_ROOT,
        keys.RUN_ID,
    ),
    writes=(keys.FINGERPRINT_DELIVERED,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC}),
    preflight=stages.always_ready,
    apply=apply,
)

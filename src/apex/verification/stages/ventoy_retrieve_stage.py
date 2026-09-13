"""Bring the medium home and accept it only when the report and its digest bind it."""

from __future__ import annotations

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import commands, errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset
from apex.verification import probing, ventoymedia, verifykeys


def for_case(case: probing.ProbeCase) -> stages.SimpleStage[portset.HostPorts]:
    observed = verifykeys.observed(case)

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        root = context.facts[composition_keys.RUNTIME_ROOT]
        run = context.facts[composition_keys.RUN_ID]
        guest = context.facts[verifykeys.GUEST]
        output = context.facts[verifykeys.WORK].joined("output")
        context.ports.guest.run(
            guest,
            guestshell.GuestRun(
                script=guestshell.RemoteScript.of(
                    guestshell.Step(
                        commands.Argv.of(
                            "sudo", "chown", "-R", defaults.BUILDER_OWNER, str(output)
                        ),
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
                guest, remote=output, into=exports.directory(root, run), recursive=True,
                deadline=defaults.TRANSFER_DEADLINE,
            )
            image, _ = ventoymedia.bind(
                context.ports, root, run, context.facts[verifykeys.VENTOY_PREPARED],
                context.facts[observed].observations, remote=context.facts[verifykeys.WORK],
            )
        except errors.PortFailure as failure:
            return stages.Fail(cause=failure.cause)
        except errors.Refusal as refusal:
            return stages.Fail(cause=str(refusal))
        return stages.Advance(facts={verifykeys.MEDIA: image})

    return stages.SimpleStage(
        id=identifiers.StageId("ventoy.retrieve"),
        reads=(
            verifykeys.GUEST, observed, verifykeys.WORK, verifykeys.VENTOY_PREPARED,
            composition_keys.RUNTIME_ROOT, composition_keys.RUN_ID,
        ),
        writes=(verifykeys.MEDIA,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.REMOTE_EXEC, effects.Effect.WRITES_RUNTIME}),
        preflight=stages.always_ready,
        apply=apply,
    )

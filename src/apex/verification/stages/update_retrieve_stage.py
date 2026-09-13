"""Bring the update fixture's output home; the archive and the key must be the reported ones."""

from __future__ import annotations

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import commands, errors, identifiers, safepaths
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset
from apex.provisioning.fixtures import update_fixture
from apex.verification import probing, updatefixtures, verifykeys


def _own(context: stages.RunContext[portset.HostPorts], output: safepaths.RemotePath) -> None:
    context.ports.guest.run(
        context.facts[verifykeys.GUEST],
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


def _mismatch(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    home: safepaths.SafePath,
    observations: object,
) -> str | None:
    """Why the received output is not the reported fixture, or nothing when it is."""
    try:
        report = update_fixture.parse_report(observations if isinstance(observations, dict) else {})
        for name, expected in (
            (updatefixtures.PAYLOADS_NAME, report.archive),
            (updatefixtures.PUBLIC_KEY_NAME, report.public_key),
        ):
            found = ports.digests.file(
                safepaths.SafePath.regular_file(home.path / name, within=root)
            )
            if found != expected:
                return f"{name}: checksum mismatch after the transfer"
    except (errors.Refusal, errors.PortFailure) as problem:
        return str(problem)
    return None


def for_case(case: probing.ProbeCase) -> stages.SimpleStage[portset.HostPorts]:
    observed = verifykeys.observed(case)

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        root = context.facts[composition_keys.RUNTIME_ROOT]
        run = context.facts[composition_keys.RUN_ID]
        output = context.facts[verifykeys.WORK].joined(exports.OUTPUT)
        _own(context, output)
        try:
            context.ports.guest.receive(
                context.facts[verifykeys.GUEST], remote=output, into=exports.directory(root, run),
                recursive=True, deadline=defaults.TRANSFER_DEADLINE,
            )
        except errors.PortFailure as failure:
            return stages.Fail(cause=failure.cause)
        home = exports.inside(root, run, exports.OUTPUT)
        why = _mismatch(context.ports, root, home, context.facts[observed].observations)
        if why is not None:
            return stages.Fail(cause=why)
        return stages.Advance(facts={verifykeys.FIXTURES: home})

    return stages.SimpleStage(
        id=identifiers.StageId("update.retrieve"),
        reads=(
            verifykeys.GUEST, verifykeys.WORK, observed, composition_keys.RUNTIME_ROOT,
            composition_keys.RUN_ID,
        ),
        writes=(verifykeys.FIXTURES,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.REMOTE_EXEC, effects.Effect.WRITES_RUNTIME}),
        preflight=stages.always_ready,
        apply=apply,
    )

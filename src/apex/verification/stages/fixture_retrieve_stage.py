"""Bring the two fixture disks home and prove each is the one the builder reported.

The builder's report names each output with its digest; after the copy the host digests
the files it holds and refuses a fixture that differs, so a transfer that lost bytes is
never handed to a test as a disk.
"""

from __future__ import annotations

from collections.abc import Mapping

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import commands, errors, identifiers, safepaths
from apex.model import builds
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset
from apex.provisioning.fixtures import installer_fixture
from apex.verification import probing, verifykeys

DIGESTS = "sha256"
EXPECTED = frozenset({installer_fixture.OTHER_IMAGE, installer_fixture.TARGET_IMAGE})


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
    reported: object,
) -> str | None:
    """Why the received outputs are not the reported ones, or nothing when they are."""
    if not isinstance(reported, Mapping) or set(reported) != EXPECTED:
        return "the builder did not report both fixture disks"
    for name, expected in reported.items():
        try:
            found = ports.digests.file(
                safepaths.SafePath.regular_file(home.path / name, within=root)
            )
        except (errors.Refusal, errors.PortFailure) as problem:
            return f"{name}: {problem}"
        if found.hex != expected:
            return f"{name}: checksum mismatch after the transfer"
    return None


def for_case(case: probing.ProbeCase) -> stages.SimpleStage[portset.HostPorts]:
    observed = verifykeys.observed(case)

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        root = context.facts[composition_keys.RUNTIME_ROOT]
        run = context.facts[composition_keys.RUN_ID]
        output = exports.remote(run).joined(builds.OUTPUT_DIRECTORY)
        _own(context, output)
        try:
            context.ports.guest.receive(
                context.facts[verifykeys.GUEST],
                remote=output,
                into=exports.directory(root, run),
                recursive=True,
                deadline=defaults.TRANSFER_DEADLINE,
            )
        except errors.PortFailure as failure:
            return stages.Fail(cause=failure.cause)
        home = exports.inside(root, run, builds.OUTPUT_DIRECTORY)
        why = _mismatch(
            context.ports, root, home, context.facts[observed].observations.get(DIGESTS)
        )
        if why is not None:
            return stages.Fail(cause=why)
        return stages.Advance(facts={verifykeys.FIXTURES: home})

    return stages.SimpleStage(
        id=identifiers.StageId("fixture.retrieve"),
        reads=(verifykeys.GUEST, observed, composition_keys.RUNTIME_ROOT, composition_keys.RUN_ID),
        writes=(verifykeys.FIXTURES,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.REMOTE_EXEC, effects.Effect.WRITES_RUNTIME}),
        preflight=stages.always_ready,
        apply=apply,
    )

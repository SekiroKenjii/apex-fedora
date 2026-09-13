"""Build the fixture's disk in the builder over the payload the agent stood in, and sign it.

The disk script reads the payload manifest the tag unit wrote and the target document the
host sent, so it needs no import step; the transcript is kept on the host as every build's is.
"""

from __future__ import annotations

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.composition.stages import run_build_stage
from apex.config import defaults
from apex.kernel import commands, identifiers, safepaths
from apex.model import builds, oci
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset
from apex.verification import verifykeys


def script(remote: safepaths.RemotePath, frozen: oci.FrozenImage) -> guestshell.RemoteScript:
    inner = guestshell.RemoteScript.of(
        guestshell.Step.of(
            "bash", f"guest/{builds.ArtifactKind.QCOW2.guest_script}",
            str(builds.ArtifactKind.QCOW2), str(frozen.image_id),
        ),
        run_build_stage.SIGN,
    )
    return guestshell.RemoteScript.of(
        guestshell.Step.of("cd", str(remote)),
        guestshell.Step.of("tar", "-xf", defaults.SOURCE_ARCHIVE_NAME),
        inner.under_lock(defaults.BUILD_LOCK),
    )


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    frozen = context.facts[composition_keys.FROZEN]
    if frozen is None:
        return stages.Fail(cause="no frozen image to build the disk from")
    completed = context.ports.guest.run(
        context.facts[composition_keys.BUILDER_VERIFIED],
        guestshell.GuestRun(
            script=script(context.facts[composition_keys.REMOTE], frozen),
            deadline=defaults.BUILD_DEADLINE,
            limit=commands.OutputLimit.default(),
            transcript=exports.inside(
                context.facts[composition_keys.RUNTIME_ROOT],
                context.facts[composition_keys.RUN_ID], builds.BUILD_LOG,
            ),
        ),
    )
    return stages.Advance(facts={composition_keys.BUILD_RUN: completed})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("fixture.disk"),
    reads=(
        composition_keys.BUILDER_VERIFIED, composition_keys.REMOTE, composition_keys.FROZEN,
        composition_keys.ACCESS, verifykeys.TAGGED, composition_keys.RUNTIME_ROOT,
        composition_keys.RUN_ID,
    ),
    writes=(composition_keys.BUILD_RUN,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC, effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)

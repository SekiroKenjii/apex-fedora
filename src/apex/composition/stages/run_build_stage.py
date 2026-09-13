"""Run the guest's build under its lock, with the transcript kept on the host.

The script is the one the older tree composed by hand, now assembled step by step: unpack the
bundle, then under the guest's build lock, bootstrap and either build the image or import the
frozen payload and derive the artifact from it. A non-zero exit is recorded, not raised, so
the output the guest did produce is still retrieved.
"""

from __future__ import annotations

from apex.composition import exports, keys
from apex.config import defaults
from apex.kernel import commands, identifiers, safepaths
from apex.model import builds, oci
from apex.pipeline import effects, stages
from apex.ports import guestshell, portset

BOOTSTRAP = guestshell.Step.of("bash", "guest/bootstrap.sh")
SIGN = guestshell.Step.of(
    "python3", "guest/sign-artifacts.py", builds.OUTPUT_DIRECTORY, builds.TARGET_DOCUMENT
)


def script(
    *,
    remote: safepaths.RemotePath,
    kind: builds.ArtifactKind,
    profile: builds.Profile,
    frozen: oci.FrozenImage | None,
    parent: identifiers.BuildId | None,
) -> guestshell.RemoteScript:
    inner = guestshell.RemoteScript.of(BOOTSTRAP, *_build_steps(kind, profile, frozen, parent))
    return guestshell.RemoteScript.of(
        guestshell.Step.of("cd", str(remote)),
        guestshell.Step.of("tar", "-xf", defaults.SOURCE_ARCHIVE_NAME),
        inner.under_lock(defaults.BUILD_LOCK),
    )


def _build_steps(
    kind: builds.ArtifactKind,
    profile: builds.Profile,
    frozen: oci.FrozenImage | None,
    parent: identifiers.BuildId | None,
) -> tuple[guestshell.Step, ...]:
    if frozen is None or parent is None:
        return (guestshell.Step.of("bash", f"guest/{kind.guest_script}", str(profile), str(kind)),)
    payload = str(exports.payload(parent, profile))
    derive = ["bash", f"guest/{kind.guest_script}", str(kind), str(frozen.image_id)]
    if kind is builds.ArtifactKind.INSTALLER:
        derive.append(payload)
    return (
        guestshell.Step.of("bash", "guest/import-payload.sh", payload, builds.TARGET_DOCUMENT),
        guestshell.Step.of(*derive),
        SIGN,
    )


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    root = context.facts[keys.RUNTIME_ROOT]
    run = context.facts[keys.RUN_ID]
    completed = context.ports.guest.run(
        context.facts[keys.BUILDER_VERIFIED],
        guestshell.GuestRun(
            script=script(
                remote=context.facts[keys.REMOTE],
                kind=context.facts[keys.KIND],
                profile=context.facts[keys.BUILD_PROFILE],
                frozen=context.facts[keys.FROZEN],
                parent=context.facts[keys.PARENT],
            ),
            deadline=defaults.BUILD_DEADLINE,
            limit=commands.OutputLimit.default(),
            transcript=exports.inside(root, run, builds.BUILD_LOG),
        ),
    )
    return stages.Advance(facts={keys.BUILD_RUN: completed})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("build.run"),
    reads=(
        keys.BUILDER_VERIFIED, keys.REMOTE, keys.TRANSFERRED, keys.ACCESS, keys.KIND,
        keys.BUILD_PROFILE, keys.FROZEN, keys.PARENT, keys.RUNTIME_ROOT, keys.RUN_ID,
    ),
    writes=(keys.BUILD_RUN,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC, effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)

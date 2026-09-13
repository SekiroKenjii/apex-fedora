"""Freeze image A of a completed update fixture as the target a fresh disk is built from.

The fixture's exported manifest must hash to the digest the report gives image A; the
target document then names that digest, A's configuration identifier and the control
profile, and says the disk is never ready to install. A second document beside the run
names the fixture the disk came from, for the reader who finds the disk later.
"""

from __future__ import annotations

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.config import defaults
from apex.kernel import encoding, errors, identifiers
from apex.model import builds, oci
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.verification import updatefixtures, verifykeys

VERSION = "a"


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    root = context.facts[composition_keys.RUNTIME_ROOT]
    run = context.facts[composition_keys.RUN_ID]
    located = context.facts[verifykeys.FIXTURE]
    try:
        updatefixtures.require_manifest(context.ports, root, located, VERSION)
    except errors.Refusal as refusal:
        return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
    image = located.image_a
    frozen = oci.FrozenImage(
        profile=str(builds.Profile.FEDORA), digest=image.digest, image_id=image.config
    )
    target: encoding.Document = {
        "digest": str(frozen.digest), "image_id": str(frozen.image_id),
        "profile": frozen.profile, "fixture": str(located.report.run),
        "ready_to_install": False,
    }
    context.ports.files.write_atomic(
        exports.inside(root, run, builds.TARGET_DOCUMENT),
        encoding.canonical(target) + b"\n", mode=defaults.RECORD_MODE,
    )
    context.ports.files.write_atomic(
        exports.inside(root, run, defaults.FIXTURE_DISK_NAME),
        encoding.canonical({
            "parent_fixture": str(located.report.run), "digest": str(frozen.digest),
            "kind": str(builds.ArtifactKind.QCOW2), "test_access": True,
            "scope": defaults.FIXTURE_DISK_SCOPE,
        }) + b"\n",
        mode=defaults.RECORD_MODE,
    )
    return stages.Advance(facts={
        composition_keys.FROZEN: frozen, composition_keys.BUILD_PROFILE: builds.Profile.FEDORA,
    })


STAGE = stages.SimpleStage(
    id=identifiers.StageId("fixture.source"),
    reads=(verifykeys.FIXTURE, composition_keys.RUNTIME_ROOT, composition_keys.RUN_ID),
    writes=(composition_keys.FROZEN, composition_keys.BUILD_PROFILE),
    attests=frozenset(),
    effects=frozenset({effects.Effect.READS_HOST, effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)

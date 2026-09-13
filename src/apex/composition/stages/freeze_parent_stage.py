"""Decide what is being built from, before any guest is touched.

An image build takes the requested profile and no parent. A derived artifact takes its
profile from the parent's frozen document, which is accepted only when the record, the
document and the packaged manifest agree. The refusals here happen in preflight, so a
request that cannot be built never opens a session.
"""

from __future__ import annotations

from apex.composition import exports, keys
from apex.config import defaults
from apex.kernel import errors, identifiers, refusals, safepaths
from apex.model import builds, oci
from apex.pipeline import effects, stages
from apex.ports import portset


def preflight(context: stages.RunContext[portset.HostPorts]) -> stages.Preflight:
    kind = context.facts[keys.KIND]
    parent = context.facts[keys.PARENT]
    if not kind.derived:
        profile = context.facts[keys.REQUESTED_PROFILE]
        if not profile.reviewed:
            return stages.RefuseBecause(
                refusals.RefusalReason.BUILD_PROFILE_NOT_REVIEWED,
                detail=f"{profile} needs a reviewed kernel lock and matching modules first",
            )
        return stages.Ready()
    if parent is None:
        return stages.RefuseBecause(
            refusals.RefusalReason.BUILD_PARENT_REQUIRED,
            detail=f"a {kind} artifact is derived from a completed image build",
        )
    return stages.Ready()


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    kind = context.facts[keys.KIND]
    parent = context.facts[keys.PARENT]
    if not kind.derived or parent is None:
        return stages.Advance(
            facts={keys.FROZEN: None, keys.BUILD_PROFILE: context.facts[keys.REQUESTED_PROFILE]}
        )
    root = context.facts[keys.RUNTIME_ROOT]
    try:
        found = frozen(context.ports, root, parent)
    except errors.Refusal as refusal:
        return stages.Refuse(refusal.reason, detail=refusal.subject)
    context.ports.files.write_atomic(
        exports.inside(root, context.facts[keys.RUN_ID], builds.TARGET_DOCUMENT),
        image_document(context.ports, root, parent),
        mode=defaults.RECORD_MODE,
    )
    return stages.Advance(
        facts={keys.FROZEN: found, keys.BUILD_PROFILE: builds.Profile(found.profile)}
    )


def image_document(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, parent: identifiers.BuildId
) -> bytes:
    """The parent's image document as it was written, which becomes a run's target document."""
    return _read(ports, exports.inside(root, parent, _output(builds.IMAGE_DOCUMENT)))


def frozen(
    ports: portset.HostPorts, root: safepaths.RuntimeRoot, parent: identifiers.BuildId
) -> oci.FrozenImage:
    """The parent's frozen image, accepted only when its record, document and manifest agree."""
    names = (builds.RECORD_NAME, _output(builds.IMAGE_DOCUMENT), _output(builds.MANIFEST_DOCUMENT))
    documents = []
    for name in names:
        path = exports.inside(root, parent, name)
        if not ports.files.exists(path):
            raise errors.Refusal(
                refusals.RefusalReason.BUILD_PARENT_NOT_COMPLETE,
                subject=f"build {parent} left no {name}",
            )
        documents.append(_read(ports, path))
    record = builds.BuildRecord.parse(documents[0])
    image = oci.FrozenImage.parse(documents[1])
    return builds.require_frozen(record, image, documents[2])


def _read(ports: portset.HostPorts, path: safepaths.SafePath) -> bytes:
    return ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)


def _output(name: str) -> str:
    return f"{builds.OUTPUT_DIRECTORY}/{name}"


STAGE = stages.SimpleStage(
    id=identifiers.StageId("build.freeze"),
    reads=(keys.KIND, keys.PARENT, keys.REQUESTED_PROFILE, keys.RUNTIME_ROOT, keys.RUN_ID),
    writes=(keys.FROZEN, keys.BUILD_PROFILE),
    attests=frozenset(),
    effects=frozenset({effects.Effect.READS_HOST, effects.Effect.WRITES_RUNTIME}),
    preflight=preflight,
    apply=apply,
)

"""The image under test is the parent build's frozen one, and its digest is the candidate.

A fingerprint run tests the packages of one completed image build, not the selected
candidate, so the record it makes names that build's digest. The parent's image document
is copied under this run's exports as the target document the guest reads, exactly as a
derived build receives it.
"""

from __future__ import annotations

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.composition.stages import freeze_parent_stage
from apex.config import defaults
from apex.kernel import errors, identifiers
from apex.model import builds
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.verification import verifykeys


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    root = context.facts[composition_keys.RUNTIME_ROOT]
    parent = context.facts[verifykeys.PARENT]
    try:
        frozen = freeze_parent_stage.frozen(context.ports, root, parent)
    except errors.Refusal as refusal:
        return stages.Refuse(refusal.reason, detail=refusal.subject)
    context.ports.files.write_atomic(
        exports.inside(root, context.facts[composition_keys.RUN_ID], builds.TARGET_DOCUMENT),
        freeze_parent_stage.image_document(context.ports, root, parent),
        mode=defaults.RECORD_MODE,
    )
    return stages.Advance(facts={verifykeys.TARGET: frozen, verifykeys.CANDIDATE: frozen.digest})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("target.freeze"),
    reads=(verifykeys.PARENT, composition_keys.RUNTIME_ROOT, composition_keys.RUN_ID),
    writes=(verifykeys.TARGET, verifykeys.CANDIDATE),
    attests=frozenset(),
    effects=frozenset({effects.Effect.READS_HOST, effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)

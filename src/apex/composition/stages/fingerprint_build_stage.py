"""Run the fingerprint image's build once the tested packages are in place beside the sources."""

from __future__ import annotations

from apex.composition import keys
from apex.composition.stages import run_build_stage
from apex.kernel import identifiers
from apex.pipeline import effects, stages
from apex.ports import portset

STAGE: stages.SimpleStage[portset.HostPorts] = stages.SimpleStage(
    id=identifiers.StageId("fingerprint.build"),
    reads=(*run_build_stage.STAGE.reads, keys.FINGERPRINT_DELIVERED),
    writes=(keys.BUILD_RUN,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.REMOTE_EXEC, effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=run_build_stage.apply,
)

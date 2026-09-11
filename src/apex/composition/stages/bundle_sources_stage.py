"""Bundle the located sources into the run's export directory, screening every file."""

from __future__ import annotations

from apex.composition import keys, screening
from apex.config import defaults
from apex.kernel import errors, identifiers
from apex.pipeline import effects, stages
from apex.ports import portset


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    run_id = context.facts[keys.RUN_ID]
    target = context.facts[keys.RUNTIME_ROOT].child(
        f"{defaults.EXPORT_DIRECTORY}/{run_id}/{defaults.SOURCE_ARCHIVE_NAME}"
    )
    try:
        bundle = context.ports.archives.bundle(
            context.facts[keys.SOURCE_SET], into=target, screen=screening.screen
        )
    except errors.Refusal as refusal:
        return stages.Refuse(refusal.reason, detail=refusal.subject)
    return stages.Advance(facts={keys.SOURCE_BUNDLE: bundle})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("source.bundle"),
    reads=(keys.RUN_ID, keys.RUNTIME_ROOT, keys.SOURCE_SET),
    writes=(keys.SOURCE_BUNDLE,),
    attests=frozenset(),
    effects=frozenset({effects.Effect.READS_HOST, effects.Effect.WRITES_RUNTIME}),
    preflight=stages.always_ready,
    apply=apply,
)

"""Name the paths of the repository that a build is reproduced from."""

from __future__ import annotations

from apex.composition import keys
from apex.config import defaults
from apex.kernel import identifiers
from apex.pipeline import stages
from apex.ports import archives, portset


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    declared = archives.SourceSet(
        root=context.facts[keys.REPOSITORY], relative_paths=defaults.SOURCE_PATHS
    )
    return stages.Advance(facts={keys.SOURCE_SET: declared})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("source.locate"),
    reads=(keys.REPOSITORY,),
    writes=(keys.SOURCE_SET,),
    attests=frozenset(),
    effects=frozenset(),
    preflight=stages.always_ready,
    apply=apply,
)

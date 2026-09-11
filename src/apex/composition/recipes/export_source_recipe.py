"""Export the repository as a screened, deterministic source bundle with its manifest.

The caller supplies the repository and the runtime root. Everything else, including the
run identifier and the export location, is produced by a stage and read by the next.
"""

from __future__ import annotations

from apex.composition import keys
from apex.composition.stages import (
    bundle_sources_stage,
    identify_run_stage,
    locate_sources_stage,
    write_manifest_stage,
)
from apex.kernel import safepaths
from apex.pipeline import plans, runner
from apex.ports import portset

NAME = "export-source"
STAGES = (
    identify_run_stage.STAGE,
    locate_sources_stage.STAGE,
    bundle_sources_stage.STAGE,
    write_manifest_stage.STAGE,
)
SEEDS = frozenset({keys.REPOSITORY, keys.RUNTIME_ROOT})
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def export(
    ports: portset.HostPorts,
    *,
    repository: safepaths.SourceRoot,
    runtime_root: safepaths.RuntimeRoot,
) -> runner.Outcome:
    return runner.run(
        PLAN,
        ports=ports,
        seeds={keys.REPOSITORY: repository, keys.RUNTIME_ROOT: runtime_root},
    )

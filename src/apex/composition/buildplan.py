"""The stages every build shares. A recipe names the plan and seeds what the operator chose."""

from __future__ import annotations

from apex.composition import keys
from apex.composition.stages import (
    acquire_sources_stage,
    bundle_sources_stage,
    check_builder_stage,
    freeze_parent_stage,
    identify_run_stage,
    locate_sources_stage,
    prepare_remote_stage,
    record_result_stage,
    retrieve_output_stage,
    review_sources_stage,
    run_build_stage,
    test_access_stage,
    transfer_sources_stage,
    write_manifest_stage,
)
from apex.kernel import identifiers, safepaths
from apex.model import builds
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset

STAGES = (
    identify_run_stage.STAGE,
    freeze_parent_stage.STAGE,
    check_builder_stage.STAGE,
    review_sources_stage.STAGE,
    acquire_sources_stage.STAGE,
    locate_sources_stage.STAGE,
    bundle_sources_stage.STAGE,
    write_manifest_stage.STAGE,
    prepare_remote_stage.STAGE,
    transfer_sources_stage.STAGE,
    test_access_stage.STAGE,
    run_build_stage.STAGE,
    retrieve_output_stage.STAGE,
    record_result_stage.STAGE,
)
SEEDS = frozenset(
    {
        keys.REPOSITORY,
        keys.RUNTIME_ROOT,
        keys.BUILDER,
        keys.REQUESTED_PROFILE,
        keys.KIND,
        keys.PARENT,
        keys.TEST_ACCESS,
    }
)


def plan(name: str) -> plans.Plan[portset.HostPorts]:
    return plans.Plan.of(name, STAGES, seeds=SEEDS)


def run(
    plan_: plans.Plan[portset.HostPorts],
    ports: portset.HostPorts,
    *,
    repository: safepaths.SourceRoot,
    runtime_root: safepaths.RuntimeRoot,
    builder: guestshell.GuestTarget,
    profile: builds.Profile,
    kind: builds.ArtifactKind,
    parent: identifiers.BuildId | None,
    test_access: bool = False,
) -> runner.Outcome:
    return runner.run(
        plan_,
        ports=ports,
        seeds={
            keys.REPOSITORY: repository,
            keys.RUNTIME_ROOT: runtime_root,
            keys.BUILDER: builder,
            keys.REQUESTED_PROFILE: profile,
            keys.KIND: kind,
            keys.PARENT: parent,
            keys.TEST_ACCESS: test_access,
        },
    )

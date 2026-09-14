"""Build a fresh QCOW2 with a disposable account from image A of a signed update fixture.

The build plan every artifact shares, with the frozen image taken from the fixture's report
instead of a parent build, the agent delivered so image A is stood in as the payload from
the builder's own store, and the disk script run over it. The record is the disk's, the
fixture it came from is named beside it, and the disk is never a candidate.
"""

from __future__ import annotations

from apex.composition import buildplan
from apex.composition import keys as composition_keys
from apex.composition.stages import freeze_parent_stage, run_build_stage
from apex.kernel import safepaths
from apex.model import builds
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset
from apex.verification import updatefixtures, verifykeys
from apex.verification.stages import (
    builder_guard_stage,
    deliver_agent_stage,
    fixture_disk_stage,
    fixture_source_stage,
    tag_payload_stage,
)

NAME = "build-recovery-disk"
REPLACED = (freeze_parent_stage.STAGE, run_build_stage.STAGE)
STAGES = (
    *(stage for stage in buildplan.STAGES if stage not in REPLACED),
    builder_guard_stage.STAGE,
    deliver_agent_stage.STAGE,
    fixture_source_stage.STAGE,
    tag_payload_stage.STAGE,
    fixture_disk_stage.STAGE,
)
SEEDS = frozenset({*buildplan.SEEDS, verifykeys.BUILDER, verifykeys.WHEEL, verifykeys.FIXTURE})
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def build(
    ports: portset.HostPorts,
    *,
    repository: safepaths.SourceRoot,
    runtime_root: safepaths.RuntimeRoot,
    builder: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    fixture: updatefixtures.Located,
) -> runner.Outcome:
    return runner.run(
        PLAN,
        ports=ports,
        seeds={
            composition_keys.REPOSITORY: repository,
            composition_keys.RUNTIME_ROOT: runtime_root,
            composition_keys.BUILDER: builder,
            composition_keys.REQUESTED_PROFILE: builds.Profile.FEDORA,
            composition_keys.KIND: builds.ArtifactKind.QCOW2,
            composition_keys.PARENT: None,
            composition_keys.TEST_ACCESS: True,
            verifykeys.BUILDER: builder,
            verifykeys.WHEEL: wheel,
            verifykeys.FIXTURE: fixture,
        },
    )

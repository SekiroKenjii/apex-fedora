"""Build the NVIDIA packages for one frozen image in the builder, and bind the result to it.

The build plan every artifact shares, with the reviewed lock read and the parent's compiler
checked before the guest is asked, and the record written only once the host has bound the
guest's report to the image, the lock and the package set. Nothing is signed and nothing
is ready to install; the older tool said the same.
"""

from __future__ import annotations

from apex.composition import buildplan
from apex.composition.stages import (
    nvidia_lock_stage,
    nvidia_record_stage,
    record_result_stage,
)
from apex.kernel import identifiers, safepaths
from apex.model import builds
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset

NAME = "build-nvidia"
STAGES = (
    *(stage for stage in buildplan.STAGES if stage is not record_result_stage.STAGE),
    nvidia_lock_stage.STAGE,
    nvidia_record_stage.STAGE,
)
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=buildplan.SEEDS)


def build(
    ports: portset.HostPorts,
    *,
    repository: safepaths.SourceRoot,
    runtime_root: safepaths.RuntimeRoot,
    builder: guestshell.GuestTarget,
    parent: identifiers.BuildId,
) -> runner.Outcome:
    return buildplan.run(
        PLAN, ports, repository=repository, runtime_root=runtime_root, builder=builder,
        profile=builds.Profile.FEDORA, kind=builds.ArtifactKind.NVIDIA, parent=parent,
    )

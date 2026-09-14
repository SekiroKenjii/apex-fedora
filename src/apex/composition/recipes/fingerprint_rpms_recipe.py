"""Rebuild the reviewed fingerprint packages with their patches in the builder, and bind the result.

The build plan every artifact shares, from the sources alone with no parent, and the record
written only once the host has bound the guest's report to the checkout's lock and patches
and digested every package it left. Nothing is signed and nothing is ready to install.
"""

from __future__ import annotations

from apex.composition import buildplan
from apex.composition.stages import fingerprint_rpm_record_stage, record_result_stage
from apex.kernel import safepaths
from apex.model import builds
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset

NAME = "build-fingerprint-rpms"
STAGES = (
    *(stage for stage in buildplan.STAGES if stage is not record_result_stage.STAGE),
    fingerprint_rpm_record_stage.STAGE,
)
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=buildplan.SEEDS)


def build(
    ports: portset.HostPorts,
    *,
    repository: safepaths.SourceRoot,
    runtime_root: safepaths.RuntimeRoot,
    builder: guestshell.GuestTarget,
) -> runner.Outcome:
    return buildplan.run(
        PLAN,
        ports,
        repository=repository,
        runtime_root=runtime_root,
        builder=builder,
        profile=builds.Profile.FEDORA,
        kind=builds.ArtifactKind.FINGERPRINT_RPMS,
        parent=None,
    )

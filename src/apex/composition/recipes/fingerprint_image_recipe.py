"""Derive a development image from the frozen control image with the tested fingerprint packages.

The parent must verify against the development key, the dialog test and the package build
must agree on the patch, and the three packages the image installs are bound by digest
before anything is sent; the builder installs them offline over the imported payload and
signs the output, which the host verifies again before the record says PASS.
"""

from __future__ import annotations

from apex.composition import buildplan, keys
from apex.composition.stages import (
    fingerprint_build_stage,
    fingerprint_deliver_stage,
    fingerprint_image_record_stage,
    fingerprint_inputs_stage,
    record_result_stage,
    run_build_stage,
)
from apex.kernel import identifiers, safepaths
from apex.model import builds
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset

NAME = "build-fingerprint-image"
REPLACED = (run_build_stage.STAGE, record_result_stage.STAGE)
STAGES = (
    *(stage for stage in buildplan.STAGES if stage not in REPLACED),
    fingerprint_inputs_stage.STAGE,
    fingerprint_deliver_stage.STAGE,
    fingerprint_build_stage.STAGE,
    fingerprint_image_record_stage.STAGE,
)
SEEDS = frozenset({*buildplan.SEEDS, keys.RPM_BUILD, keys.GTK_TEST})
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def build(
    ports: portset.HostPorts,
    *,
    repository: safepaths.SourceRoot,
    runtime_root: safepaths.RuntimeRoot,
    builder: guestshell.GuestTarget,
    parent: identifiers.BuildId,
    rpm_build: identifiers.BuildId,
    gtk_test: identifiers.BuildId,
) -> runner.Outcome:
    return runner.run(
        PLAN,
        ports=ports,
        seeds={
            keys.REPOSITORY: repository,
            keys.RUNTIME_ROOT: runtime_root,
            keys.BUILDER: builder,
            keys.REQUESTED_PROFILE: builds.Profile.FEDORA,
            keys.KIND: builds.ArtifactKind.FINGERPRINT_IMAGE,
            keys.PARENT: parent,
            keys.TEST_ACCESS: False,
            keys.RPM_BUILD: rpm_build,
            keys.GTK_TEST: gtk_test,
        },
    )

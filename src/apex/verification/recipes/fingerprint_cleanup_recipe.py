"""Run the fingerprint cleanup fault in the isolated builder and record one result for it.

The builder proves itself, the agent is delivered, the pinned upstream tests are fetched on
the host, the parent build's image is frozen as the target and its digest becomes the
candidate, the work directory is laid out in the builder, the parent's archive is imported
into the builder's store, and then the fault runs over it; its report is the one proof
behind `fingerprint.virtual-cleanup`.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import claims, identifiers, safepaths
from apex.pipeline import plans, runner, stages
from apex.ports import guestshell, portset
from apex.verification import faults, recording, verifykeys
from apex.verification.stages import (
    acquire_tests_stage,
    builder_guard_stage,
    deliver_agent_stage,
    fault_stage,
    fingerprint_work_stage,
    import_payload_stage,
    mint_stage,
    target_image_stage,
)

NAME = "verify-fingerprint-cleanup"
CHECK = identifiers.CheckId("fingerprint.virtual-cleanup")
CASE = faults.lookup(identifiers.ProbeId("fault.fingerprint-cleanup"))
WORK = "work"


def _arguments(context: stages.RunContext[portset.HostPorts]) -> dict[str, str]:
    return {WORK: str(context.facts[verifykeys.WORK])}


STAGES = (
    identify_run_stage.STAGE,
    builder_guard_stage.STAGE,
    deliver_agent_stage.STAGE,
    acquire_tests_stage.STAGE,
    target_image_stage.STAGE,
    fingerprint_work_stage.STAGE,
    import_payload_stage.STAGE,
    fault_stage.for_case(CASE, arguments=_arguments, after=(verifykeys.WORK, verifykeys.IMPORTED)),
    mint_stage.for_check(CHECK, reports=[verifykeys.fault_report(CASE)]),
)
SEEDS = frozenset(
    {
        verifykeys.BUILDER,
        verifykeys.WHEEL,
        verifykeys.WITNESS,
        verifykeys.RECORDER,
        verifykeys.PARENT,
        composition_keys.RUNTIME_ROOT,
        composition_keys.REPOSITORY,
    }
)
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def verify(
    ports: portset.HostPorts,
    *,
    builder: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    parent: identifiers.BuildId,
    witness: claims.EnvironmentKind,
    recorder: recording.Recorder,
    root: safepaths.RuntimeRoot,
    repository: safepaths.SourceRoot,
) -> runner.Outcome:
    return runner.run(
        PLAN,
        ports=ports,
        seeds={
            verifykeys.BUILDER: builder,
            verifykeys.WHEEL: wheel,
            verifykeys.WITNESS: witness,
            verifykeys.RECORDER: recorder,
            verifykeys.PARENT: parent,
            composition_keys.RUNTIME_ROOT: root,
            composition_keys.REPOSITORY: repository,
        },
    )

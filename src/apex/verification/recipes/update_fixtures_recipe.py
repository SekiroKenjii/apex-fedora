"""Build the signed A and B images over the frozen control image in the isolated builder.

The builder proves itself, the agent is delivered, the parent's image is frozen as the
target, the work directory is laid out with the target document, the grub repair script
and the reviewed retry preset, the payload is imported into the builder's store, the
fixture unit builds, checks and signs both images and packages the bundle, the output is
received and its archive and public key are digested against the report, and the report
is retained beside them. Nothing is minted: a fixture is an input to later tests.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import identifiers, safepaths
from apex.pipeline import plans, runner, stages
from apex.ports import guestshell, portset
from apex.verification import probes, verifykeys
from apex.verification.stages import (
    builder_guard_stage,
    deliver_agent_stage,
    import_payload_stage,
    probe_stage,
    retain_report_stage,
    target_image_stage,
    update_retrieve_stage,
    update_work_stage,
)

NAME = "build-update-fixtures"
CASE = probes.lookup(identifiers.ProbeId("fixture.update"))
WORK = "work"


def _arguments(context: stages.RunContext[portset.HostPorts]) -> dict[str, str]:
    return {WORK: str(context.facts[verifykeys.WORK])}


STAGES = (
    identify_run_stage.STAGE,
    builder_guard_stage.STAGE,
    deliver_agent_stage.STAGE,
    target_image_stage.STAGE,
    update_work_stage.STAGE,
    import_payload_stage.STAGE,
    probe_stage.for_case(CASE, arguments=_arguments, after=(verifykeys.WORK, verifykeys.IMPORTED)),
    update_retrieve_stage.for_case(CASE),
    retain_report_stage.for_probe(CASE),
)
SEEDS = frozenset({
    verifykeys.BUILDER, verifykeys.WHEEL, verifykeys.PARENT, composition_keys.RUNTIME_ROOT,
    composition_keys.REPOSITORY,
})
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def build(
    ports: portset.HostPorts,
    *,
    builder: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    parent: identifiers.BuildId,
    root: safepaths.RuntimeRoot,
    repository: safepaths.SourceRoot,
) -> runner.Outcome:
    return runner.run(
        PLAN,
        ports=ports,
        seeds={
            verifykeys.BUILDER: builder,
            verifykeys.WHEEL: wheel,
            verifykeys.PARENT: parent,
            composition_keys.RUNTIME_ROOT: root,
            composition_keys.REPOSITORY: repository,
        },
    )

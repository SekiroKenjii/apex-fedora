"""Share a completed update fixture's identical blobs in the idle builder, and keep the report."""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import identifiers, safepaths
from apex.pipeline import plans, runner, stages
from apex.ports import guestshell, portset
from apex.provisioning.fixtures import dedupe_fixture
from apex.verification import probes, verifykeys
from apex.verification.stages import (
    builder_guard_stage,
    deliver_agent_stage,
    probe_stage,
    retain_report_stage,
)

NAME = "verify-dedupe"
CASE = probes.lookup(identifiers.ProbeId("fixture.dedupe"))
WORK_PREFIX = f"{dedupe_fixture.SCRATCH}/apex-dedupe-"


def _arguments(context: stages.RunContext[portset.HostPorts]) -> dict[str, str]:
    return {
        "work": f"{WORK_PREFIX}{context.facts[composition_keys.RUN_ID]}",
        "fixture": str(context.facts[verifykeys.PARENT]),
    }


STAGES = (
    identify_run_stage.STAGE,
    builder_guard_stage.STAGE,
    deliver_agent_stage.STAGE,
    probe_stage.for_case(CASE, arguments=_arguments, after=(verifykeys.PARENT,)),
    retain_report_stage.for_probe(CASE),
)
SEEDS = frozenset({
    verifykeys.BUILDER, verifykeys.WHEEL, verifykeys.PARENT, composition_keys.RUNTIME_ROOT,
})
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def verify(
    ports: portset.HostPorts,
    *,
    builder: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    parent: identifiers.BuildId,
    root: safepaths.RuntimeRoot,
) -> runner.Outcome:
    return runner.run(
        PLAN,
        ports=ports,
        seeds={
            verifykeys.BUILDER: builder,
            verifykeys.WHEEL: wheel,
            verifykeys.PARENT: parent,
            composition_keys.RUNTIME_ROOT: root,
        },
    )

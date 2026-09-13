"""Make the two installer fixture disks in the isolated builder and bring them home checked.

The builder proves itself, the agent is delivered, the fixture unit runs under the run's
directory, the outputs are received and each is digested against the builder's report,
and the report is retained beside them.
"""

from __future__ import annotations

from apex.composition import exports
from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import identifiers, safepaths
from apex.model import builds
from apex.pipeline import plans, runner, stages
from apex.ports import guestshell, portset
from apex.verification import probes, verifykeys
from apex.verification.stages import (
    builder_guard_stage,
    deliver_agent_stage,
    fixture_retrieve_stage,
    probe_stage,
    retain_report_stage,
)

NAME = "build-installer-fixtures"
CASE = probes.lookup(identifiers.ProbeId("fixture.installer-disks"))
WORK_DIRECTORY = "work"


def _arguments(context: stages.RunContext[portset.HostPorts]) -> dict[str, str]:
    run = context.facts[composition_keys.RUN_ID]
    remote = exports.remote(run)
    return {
        "work": str(remote.joined(WORK_DIRECTORY)),
        "output": str(remote.joined(builds.OUTPUT_DIRECTORY)),
        "token": str(run),
    }


STAGES = (
    identify_run_stage.STAGE,
    builder_guard_stage.STAGE,
    deliver_agent_stage.STAGE,
    probe_stage.for_case(CASE, arguments=_arguments, after=(composition_keys.RUN_ID,)),
    fixture_retrieve_stage.for_case(CASE),
    retain_report_stage.for_probe(CASE),
)
SEEDS = frozenset({verifykeys.BUILDER, verifykeys.WHEEL, composition_keys.RUNTIME_ROOT})
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def build(
    ports: portset.HostPorts,
    *,
    builder: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    root: safepaths.RuntimeRoot,
) -> runner.Outcome:
    return runner.run(
        PLAN,
        ports=ports,
        seeds={
            verifykeys.BUILDER: builder,
            verifykeys.WHEEL: wheel,
            composition_keys.RUNTIME_ROOT: root,
        },
    )

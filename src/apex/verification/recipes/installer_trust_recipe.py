"""Run the installer trust fault in the isolated builder and keep its report with the run.

No catalogue check names this fault, so nothing is minted: the builder proves itself, the
agent is delivered, a work directory is made, the fault runs over it, and the report and
its verdict are written under the run's exports for the reader who asked.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import identifiers, safepaths
from apex.pipeline import plans, runner, stages
from apex.ports import guestshell, portset
from apex.verification import faults, verifykeys
from apex.verification.stages import (
    builder_guard_stage,
    deliver_agent_stage,
    fault_stage,
    retain_report_stage,
    trust_work_stage,
)

NAME = "verify-installer-trust"
CASE = faults.lookup(identifiers.ProbeId("fault.installer-trust"))
WORK = "work"


def _arguments(context: stages.RunContext[portset.HostPorts]) -> dict[str, str]:
    return {WORK: str(context.facts[verifykeys.WORK])}


STAGES = (
    identify_run_stage.STAGE,
    builder_guard_stage.STAGE,
    deliver_agent_stage.STAGE,
    trust_work_stage.STAGE,
    fault_stage.for_case(CASE, arguments=_arguments, after=(verifykeys.WORK,)),
    retain_report_stage.for_case(CASE),
)
SEEDS = frozenset({verifykeys.BUILDER, verifykeys.WHEEL, composition_keys.RUNTIME_ROOT})
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def verify(
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

"""The plans that ask a guest one thing and keep the answer with the run, minting nothing.

The older `test-live-check` did this for each of its cases: transfer the probe, run it,
retain the result for the operator to cite. The shape is the same for a probe and for a
fault, so each such recipe is one line naming its case.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import safepaths
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset
from apex.verification import faulting, probing, verifykeys
from apex.verification.stages import (
    deliver_agent_stage,
    fault_stage,
    probe_stage,
    retain_report_stage,
)

SEEDS = frozenset({verifykeys.GUEST, verifykeys.WHEEL, composition_keys.RUNTIME_ROOT})


def probe_plan(name: str, case: probing.ProbeCase) -> plans.Plan[portset.HostPorts]:
    return plans.Plan.of(
        name,
        (
            identify_run_stage.STAGE,
            deliver_agent_stage.STAGE,
            probe_stage.for_case(case),
            retain_report_stage.for_probe(case),
        ),
        seeds=SEEDS,
    )


def fault_plan(name: str, case: faulting.FaultCase) -> plans.Plan[portset.HostPorts]:
    return plans.Plan.of(
        name,
        (
            identify_run_stage.STAGE,
            deliver_agent_stage.STAGE,
            fault_stage.for_case(case),
            retain_report_stage.for_case(case),
        ),
        seeds=SEEDS,
    )


def run(
    plan: plans.Plan[portset.HostPorts],
    ports: portset.HostPorts,
    *,
    guest: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    root: safepaths.RuntimeRoot,
) -> runner.Outcome:
    return runner.run(
        plan,
        ports=ports,
        seeds={
            verifykeys.GUEST: guest,
            verifykeys.WHEEL: wheel,
            composition_keys.RUNTIME_ROOT: root,
        },
    )

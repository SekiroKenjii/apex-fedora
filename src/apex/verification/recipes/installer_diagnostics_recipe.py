"""The installer guest's logs brought home in one step, and the run failed if any is not whole."""

from __future__ import annotations

from apex.composition.stages import identify_run_stage
from apex.kernel import identifiers, safepaths
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset
from apex.verification import probes, retaining
from apex.verification.stages import (
    deliver_agent_stage,
    installer_logs_stage,
    probe_stage,
    retain_report_stage,
)

NAME = "verify-installer-diagnostics"
CASE = probes.lookup(identifiers.ProbeId("installer.diagnostics"))
STAGES = (
    identify_run_stage.STAGE,
    deliver_agent_stage.STAGE,
    probe_stage.for_case(CASE),
    retain_report_stage.for_probe(CASE),
    installer_logs_stage.for_case(CASE),
)
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=retaining.SEEDS)


def verify(
    ports: portset.HostPorts,
    *,
    guest: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    root: safepaths.RuntimeRoot,
) -> runner.Outcome:
    return retaining.run(PLAN, ports, guest=guest, wheel=wheel, root=root)

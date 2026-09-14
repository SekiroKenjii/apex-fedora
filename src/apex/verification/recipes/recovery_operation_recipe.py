"""One recovery operation against the installed disposable guest, with its update fixture."""

from __future__ import annotations

from apex.pipeline import runner
from apex.ports import portset
from apex.verification import operationplans
from apex.verification.stages import recovery_operate_stage

NAME = "verify-recovery"
PLAN = operationplans.plan(NAME, recovery_operate_stage.STAGE)


def verify(ports: portset.HostPorts, inputs: operationplans.Inputs) -> runner.Outcome:
    return operationplans.run(PLAN, ports, inputs)

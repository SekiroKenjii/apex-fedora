"""One A/B update operation against the disposable guest, with the fixture that made it.

The guest is waited for, the agent delivered, and the operation run and judged; the report
is kept under the run. Nothing is minted: the fixture's images are not the candidate.
"""

from __future__ import annotations

from apex.pipeline import runner
from apex.ports import portset
from apex.verification import operationplans
from apex.verification.stages import update_operate_stage

NAME = "verify-update"
PLAN = operationplans.plan(NAME, update_operate_stage.STAGE)


def verify(ports: portset.HostPorts, inputs: operationplans.Inputs) -> runner.Outcome:
    return operationplans.run(PLAN, ports, inputs)

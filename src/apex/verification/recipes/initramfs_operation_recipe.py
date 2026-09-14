"""One initramfs fault operation against the installed disposable guest and its fixture."""

from __future__ import annotations

from apex.pipeline import runner
from apex.ports import portset
from apex.verification import operationplans, verifykeys
from apex.verification.stages import initramfs_operate_stage

NAME = "verify-initramfs"
PLAN = operationplans.plan(
    NAME, initramfs_operate_stage.STAGE, seeds=frozenset({verifykeys.INSPECTION})
)


def verify(ports: portset.HostPorts, inputs: operationplans.Inputs) -> runner.Outcome:
    return operationplans.run(PLAN, ports, inputs)

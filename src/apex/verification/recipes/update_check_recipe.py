"""Check the disposable guest booted into one fixture version, logged in at the greeter.

The desktop render recipe's three stages log the account in, settle the Shell and show
the render probe; the check stage then reads the state, the health and the sentinel and
judges all of it. Nothing is minted: the fixture's images are not the candidate.
"""

from __future__ import annotations

from apex.pipeline import runner
from apex.ports import portset
from apex.verification import operationplans, verifykeys
from apex.verification.recipes import desktop_render_recipe
from apex.verification.stages import update_check_stage

NAME = "verify-update-check"
PLAN = operationplans.plan(
    NAME,
    desktop_render_recipe.LOGIN,
    desktop_render_recipe.SHELL,
    desktop_render_recipe.RENDER,
    update_check_stage.STAGE,
    seeds=frozenset({verifykeys.MONITOR}),
)


def verify(ports: portset.HostPorts, inputs: operationplans.Inputs) -> runner.Outcome:
    return operationplans.run(PLAN, ports, inputs)

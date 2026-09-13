"""Log in at GDM by keyboard, settle the Shell, show the render probe, record one result.

Three judgements, one check: the password must be accepted into a Wayland session on the
seat, the Shell must report its startup and follow the Overview keys, and the GTK4 probe's
bars must be visible in the hypervisor's frame for `desktop.password-wayland` to pass. Each
stage after the login blocks itself when an earlier judgement did not pass, so the record
carries the first failure and the guest is not asked to do what it cannot.
"""

from __future__ import annotations

from apex.composition.stages import identify_run_stage
from apex.kernel import identifiers
from apex.pipeline import plans, runner
from apex.ports import portset
from apex.verification import desktopplans, probes, verifykeys
from apex.verification.stages import (
    deliver_agent_stage,
    login_stage,
    mint_stage,
    render_bars_stage,
    shell_startup_stage,
)

NAME = "verify-desktop-render"
CHECK = identifiers.CheckId("desktop.password-wayland")
LOGIN = login_stage.for_cases(
    probes.lookup(identifiers.ProbeId("desktop.session")),
    probes.lookup(identifiers.ProbeId("desktop.greeter")),
)
SHELL = shell_startup_stage.for_cases(
    probes.lookup(identifiers.ProbeId("desktop.shell-startup")),
    probes.lookup(identifiers.ProbeId("desktop.overview")),
    gates=(login_stage.KEY,),
)
RENDER = render_bars_stage.for_case(
    probes.lookup(identifiers.ProbeId("desktop.render")),
    gates=(login_stage.KEY, shell_startup_stage.KEY),
)
STAGES = (
    identify_run_stage.STAGE,
    deliver_agent_stage.STAGE,
    LOGIN,
    SHELL,
    RENDER,
    mint_stage.for_check(
        CHECK, reports=[login_stage.KEY, shell_startup_stage.KEY, render_bars_stage.KEY]
    ),
)
SEEDS = desktopplans.SEEDS | {verifykeys.CREDENTIALS}
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def verify(ports: portset.HostPorts, inputs: desktopplans.Inputs) -> runner.Outcome:
    return desktopplans.run(PLAN, ports, inputs)

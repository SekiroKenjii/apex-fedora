"""Check the disposable guest booted into one fixture version, logged in at the greeter.

The desktop render recipe's three stages log the account in, settle the Shell and show
the render probe; the check stage then reads the state, the health and the sentinel and
judges all of it. Nothing is minted: the fixture's images are not the candidate.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import safepaths
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset
from apex.verification import testaccess, updatefixtures, verifykeys
from apex.verification.recipes import desktop_render_recipe
from apex.verification.stages import deliver_agent_stage, guest_ready_stage, update_check_stage

NAME = "verify-update-check"
STAGES = (
    identify_run_stage.STAGE,
    guest_ready_stage.STAGE,
    deliver_agent_stage.waiting(verifykeys.READY),
    desktop_render_recipe.LOGIN,
    desktop_render_recipe.SHELL,
    desktop_render_recipe.RENDER,
    update_check_stage.STAGE,
)
SEEDS = frozenset({
    verifykeys.GUEST, verifykeys.WHEEL, verifykeys.FIXTURE, verifykeys.ACTION,
    verifykeys.CREDENTIALS, verifykeys.MACHINE_PROCESS, verifykeys.MONITOR,
    composition_keys.RUNTIME_ROOT,
})
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def verify(
    ports: portset.HostPorts,
    *,
    guest: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    fixture: updatefixtures.Located,
    action: str,
    credentials: testaccess.Credentials,
    process: int,
    monitor: safepaths.SafePath,
    root: safepaths.RuntimeRoot,
) -> runner.Outcome:
    return runner.run(
        PLAN,
        ports=ports,
        seeds={
            verifykeys.GUEST: guest,
            verifykeys.WHEEL: wheel,
            verifykeys.FIXTURE: fixture,
            verifykeys.ACTION: action,
            verifykeys.CREDENTIALS: credentials,
            verifykeys.MACHINE_PROCESS: process,
            verifykeys.MONITOR: monitor,
            composition_keys.RUNTIME_ROOT: root,
        },
    )

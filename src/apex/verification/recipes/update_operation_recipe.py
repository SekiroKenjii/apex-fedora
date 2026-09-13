"""One A/B update operation against the disposable guest, with the fixture that made it.

The guest is waited for, the agent delivered, and the operation run and judged; the report
is kept under the run. Nothing is minted: the fixture's images are not the candidate.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import safepaths
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset
from apex.verification import testaccess, updatefixtures, verifykeys
from apex.verification.stages import deliver_agent_stage, guest_ready_stage, update_operate_stage

NAME = "verify-update"
STAGES = (
    identify_run_stage.STAGE,
    guest_ready_stage.STAGE,
    deliver_agent_stage.waiting(verifykeys.READY),
    update_operate_stage.STAGE,
)
SEEDS = frozenset({
    verifykeys.GUEST, verifykeys.WHEEL, verifykeys.FIXTURE, verifykeys.ACTION,
    verifykeys.CREDENTIALS, verifykeys.MACHINE_PROCESS, composition_keys.RUNTIME_ROOT,
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
            composition_keys.RUNTIME_ROOT: root,
        },
    )

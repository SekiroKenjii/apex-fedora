"""One initramfs fault operation against the installed disposable guest and its fixture."""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import encoding, safepaths
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset
from apex.verification import testaccess, updatefixtures, verifykeys
from apex.verification.stages import (
    deliver_agent_stage,
    guest_ready_stage,
    initramfs_operate_stage,
)

NAME = "verify-initramfs"
STAGES = (
    identify_run_stage.STAGE,
    guest_ready_stage.STAGE,
    deliver_agent_stage.waiting(verifykeys.READY),
    initramfs_operate_stage.STAGE,
)
SEEDS = frozenset({
    verifykeys.GUEST, verifykeys.WHEEL, verifykeys.FIXTURE, verifykeys.ACTION,
    verifykeys.CREDENTIALS, verifykeys.MACHINE_PROCESS, verifykeys.INSPECTION,
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
    inspection: encoding.Document | None,
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
            verifykeys.INSPECTION: inspection,
            composition_keys.RUNTIME_ROOT: root,
        },
    )

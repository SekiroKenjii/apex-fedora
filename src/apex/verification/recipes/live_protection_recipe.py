"""Prove the live medium protects the disks it finds, and record one result for it.

Two faults, one check: the virtio fixtures and the hot-plugged USB fixture both have to deny
every write for `live.disk-protection` to pass, so both reports back one record.
"""

from __future__ import annotations

from apex.composition.stages import identify_run_stage
from apex.kernel import claims, identifiers, safepaths
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset
from apex.verification import faults, recording, verifykeys
from apex.verification.stages import deliver_agent_stage, fault_stage, mint_stage

NAME = "verify-live-protection"
CHECK = identifiers.CheckId("live.disk-protection")
CASES = (
    faults.lookup(identifiers.ProbeId("fault.live-write-denial")),
    faults.lookup(identifiers.ProbeId("fault.usb-write-denial")),
)
STAGES = (
    identify_run_stage.STAGE,
    deliver_agent_stage.STAGE,
    *(fault_stage.for_case(case) for case in CASES),
    mint_stage.for_check(
        CHECK, reports=[verifykeys.fault_report(case) for case in CASES]
    ),
)
SEEDS = frozenset({
    verifykeys.GUEST,
    verifykeys.WHEEL,
    verifykeys.CANDIDATE,
    verifykeys.WITNESS,
    verifykeys.RECORDER,
})
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def verify(
    ports: portset.HostPorts,
    *,
    guest: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    candidate: identifiers.Digest,
    witness: claims.EnvironmentKind,
    recorder: recording.Recorder,
) -> runner.Outcome:
    return runner.run(
        PLAN,
        ports=ports,
        seeds={
            verifykeys.GUEST: guest,
            verifykeys.WHEEL: wheel,
            verifykeys.CANDIDATE: candidate,
            verifykeys.WITNESS: witness,
            verifykeys.RECORDER: recorder,
        },
    )


"""The guard denied its lock at the pre-mount breakpoint, the report kept for the reader."""

from __future__ import annotations

from apex.kernel import identifiers, safepaths
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset
from apex.verification import faults, retaining

NAME = "verify-live-lock"
CASE = faults.lookup(identifiers.ProbeId("fault.live-lock"))
PLAN: plans.Plan[portset.HostPorts] = retaining.fault_plan(NAME, CASE)


def verify(
    ports: portset.HostPorts,
    *,
    guest: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    root: safepaths.RuntimeRoot,
) -> runner.Outcome:
    return retaining.run(PLAN, ports, guest=guest, wheel=wheel, root=root)

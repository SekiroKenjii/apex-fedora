"""The live medium observed from inside, its report kept for the reader who records live.direct."""

from __future__ import annotations

from apex.kernel import identifiers, safepaths
from apex.pipeline import plans, runner
from apex.ports import guestshell, portset
from apex.verification import probes, retaining

NAME = "verify-live-observe"
CASE = probes.lookup(identifiers.ProbeId("live.observe"))
PLAN: plans.Plan[portset.HostPorts] = retaining.probe_plan(NAME, CASE)


def verify(
    ports: portset.HostPorts,
    *,
    guest: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    root: safepaths.RuntimeRoot,
) -> runner.Outcome:
    return retaining.run(PLAN, ports, guest=guest, wheel=wheel, root=root)

"""The plans of the guest operations share one shape: ready, delivered, operated, kept.

Every operation waits for the guest, delivers the agent, then runs the stages of its
family; every one takes the same inputs from the command, and a family that needs more,
the monitor for a check or the reviewed inspection for an injection, names it here too.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import encoding, safepaths
from apex.pipeline import facts, plans, runner, stages
from apex.ports import guestshell, portset
from apex.verification import testaccess, updatefixtures, verifykeys
from apex.verification.stages import deliver_agent_stage, guest_ready_stage

COMMON: tuple[stages.Stage[portset.HostPorts], ...] = (
    identify_run_stage.STAGE,
    guest_ready_stage.STAGE,
    deliver_agent_stage.waiting(verifykeys.READY),
)
SEEDS: frozenset[facts.FactKey[Any]] = frozenset(
    {
        verifykeys.GUEST,
        verifykeys.WHEEL,
        verifykeys.FIXTURE,
        verifykeys.ACTION,
        verifykeys.CREDENTIALS,
        verifykeys.MACHINE_PROCESS,
        composition_keys.RUNTIME_ROOT,
    }
)


@dataclasses.dataclass(frozen=True, slots=True)
class Inputs:
    """What every operation is seeded with, and the two facts only some families read."""

    guest: guestshell.GuestTarget
    wheel: safepaths.SafePath
    fixture: updatefixtures.Located
    action: str
    credentials: testaccess.Credentials
    process: int
    root: safepaths.RuntimeRoot
    monitor: safepaths.SafePath | None = None
    inspection: encoding.Document | None = None

    def seeds(self) -> dict[facts.FactKey[Any], object]:
        seeded: dict[facts.FactKey[Any], object] = {
            verifykeys.GUEST: self.guest,
            verifykeys.WHEEL: self.wheel,
            verifykeys.FIXTURE: self.fixture,
            verifykeys.ACTION: self.action,
            verifykeys.CREDENTIALS: self.credentials,
            verifykeys.MACHINE_PROCESS: self.process,
            composition_keys.RUNTIME_ROOT: self.root,
            verifykeys.INSPECTION: self.inspection,
        }
        if self.monitor is not None:
            seeded[verifykeys.MONITOR] = self.monitor
        return seeded


def plan(
    name: str,
    *family: stages.Stage[portset.HostPorts],
    seeds: frozenset[facts.FactKey[Any]] = frozenset(),
) -> plans.Plan[portset.HostPorts]:
    return plans.Plan.of(name, (*COMMON, *family), seeds=SEEDS | seeds)


def run(
    held: plans.Plan[portset.HostPorts], ports: portset.HostPorts, inputs: Inputs
) -> runner.Outcome:
    return runner.run(held, ports=ports, seeds=inputs.seeds())

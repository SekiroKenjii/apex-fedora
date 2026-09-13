"""The desktop recipes share their seeds: a candidate, its witness, the store and the monitor."""

from __future__ import annotations

import dataclasses
from typing import Any

from apex.composition import keys as composition_keys
from apex.kernel import claims, identifiers, safepaths
from apex.pipeline import facts, plans, runner
from apex.ports import guestshell, portset
from apex.verification import recording, testaccess, verifykeys

SEEDS: frozenset[facts.FactKey[Any]] = frozenset(
    {
        verifykeys.GUEST,
        verifykeys.WHEEL,
        verifykeys.CANDIDATE,
        verifykeys.WITNESS,
        verifykeys.RECORDER,
        verifykeys.MONITOR,
        composition_keys.RUNTIME_ROOT,
    }
)


@dataclasses.dataclass(frozen=True, slots=True)
class Inputs:
    guest: guestshell.GuestTarget
    wheel: safepaths.SafePath
    candidate: identifiers.Digest
    witness: claims.EnvironmentKind
    recorder: recording.Recorder
    monitor: safepaths.SafePath
    root: safepaths.RuntimeRoot
    credentials: testaccess.Credentials | None = None

    def seeds(self) -> dict[facts.FactKey[Any], object]:
        seeded: dict[facts.FactKey[Any], object] = {
            verifykeys.GUEST: self.guest,
            verifykeys.WHEEL: self.wheel,
            verifykeys.CANDIDATE: self.candidate,
            verifykeys.WITNESS: self.witness,
            verifykeys.RECORDER: self.recorder,
            verifykeys.MONITOR: self.monitor,
            composition_keys.RUNTIME_ROOT: self.root,
        }
        if self.credentials is not None:
            seeded[verifykeys.CREDENTIALS] = self.credentials
        return seeded


def run(
    held: plans.Plan[portset.HostPorts], ports: portset.HostPorts, inputs: Inputs
) -> runner.Outcome:
    return runner.run(held, ports=ports, seeds=inputs.seeds())

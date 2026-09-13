"""The shape every desktop stage shares: the guest, the agent, the monitor, the run's home."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from apex.composition import keys as composition_keys
from apex.kernel import identifiers
from apex.pipeline import effects, facts, stages
from apex.ports import portset
from apex.verification import verifykeys

Apply = Callable[[stages.RunContext[portset.HostPorts]], stages.StageResult]


def stage(
    name: str, key: facts.FactKey[Any], apply: Apply, *, reads: Sequence[facts.FactKey[Any]] = ()
) -> stages.SimpleStage[portset.HostPorts]:
    """A stage that drives the desktop through the monitor and keeps its captures with the run."""
    return stages.SimpleStage(
        id=identifiers.StageId(name),
        reads=(
            verifykeys.GUEST,
            verifykeys.AGENT,
            verifykeys.MONITOR,
            composition_keys.RUNTIME_ROOT,
            composition_keys.RUN_ID,
            *reads,
        ),
        writes=(key,),
        attests=frozenset(),
        effects=frozenset(
            {
                effects.Effect.REMOTE_EXEC,
                effects.Effect.MUTATES_GUEST,
                effects.Effect.WRITES_RUNTIME,
            }
        ),
        preflight=stages.always_ready,
        apply=apply,
    )

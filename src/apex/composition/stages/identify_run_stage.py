"""Mint the identifier every later stage files its output under."""

from __future__ import annotations

from apex.composition import keys
from apex.kernel import identifiers
from apex.pipeline import stages
from apex.ports import portset


def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
    return stages.Advance(facts={keys.RUN_ID: context.ports.identities.run_id()})


STAGE = stages.SimpleStage(
    id=identifiers.StageId("run.identify"),
    reads=(),
    writes=(keys.RUN_ID,),
    attests=frozenset(),
    effects=frozenset(),
    preflight=stages.always_ready,
    apply=apply,
)

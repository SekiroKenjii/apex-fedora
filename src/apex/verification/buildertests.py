"""A test run in the builder over one completed build: guarded, delivered, judged, kept."""

from __future__ import annotations

from typing import Any

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import identifiers, safepaths
from apex.pipeline import facts, plans, runner
from apex.ports import guestshell, portset
from apex.verification import verifykeys
from apex.verification.stages import builder_guard_stage, builder_test_stage

SEEDS: frozenset[facts.FactKey[Any]] = frozenset(
    {
        verifykeys.BUILDER,
        verifykeys.PARENT,
        composition_keys.RUNTIME_ROOT,
        composition_keys.REPOSITORY,
    }
)


def plan(
    name: str, unit: str, *, prepare: builder_test_stage.Prepare, judge: builder_test_stage.Judge
) -> plans.Plan[portset.HostPorts]:
    return plans.Plan.of(
        name,
        (
            identify_run_stage.STAGE,
            builder_guard_stage.STAGE,
            builder_test_stage.for_test(unit, prepare=prepare, judge=judge),
        ),
        seeds=SEEDS,
    )


def run(
    held: plans.Plan[portset.HostPorts],
    ports: portset.HostPorts,
    *,
    builder: guestshell.GuestTarget,
    parent: identifiers.BuildId,
    root: safepaths.RuntimeRoot,
    repository: safepaths.SourceRoot,
) -> runner.Outcome:
    return runner.run(
        held,
        ports=ports,
        seeds={
            verifykeys.BUILDER: builder,
            verifykeys.PARENT: parent,
            composition_keys.RUNTIME_ROOT: root,
            composition_keys.REPOSITORY: repository,
        },
    )

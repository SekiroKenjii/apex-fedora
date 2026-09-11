"""Preflight purity is enforced, not requested.

A stage that acts during a dry run is a guard bypass, and the plan output is the operator's
only chance to review a run before it happens.
"""

from __future__ import annotations

import pytest

from apex.kernel import commands, errors, identifiers, timing
from apex.pipeline import effects, facts, plans, runner, stages
from apex.ports import portset

TOKEN = facts.FactKey[str]("token")


def acting_stage(during: str) -> stages.Stage[portset.HostPorts]:
    def act(context: stages.RunContext[portset.HostPorts]) -> stages.Preflight:
        context.ports.processes.run(
            commands.Argv.of("printf", "hello"),
            deadline=timing.Deadline(timing.Elapsed(1)),
            limit=commands.OutputLimit.default(),
        )
        return stages.Ready()

    def behave(context: stages.RunContext[portset.HostPorts]) -> stages.Preflight:
        return stages.Ready()

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        return stages.Advance(facts={TOKEN: "value"})

    return stages.SimpleStage(
        id=identifiers.StageId("acts"),
        reads=(),
        writes=(TOKEN,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.READS_HOST}),
        preflight=act if during == "preflight" else behave,
        apply=apply,
    )


def test_a_stage_that_runs_a_program_during_preflight_is_a_defect(
    ports: portset.HostPorts,
) -> None:
    plan = plans.Plan.of("demo", [acting_stage("preflight")])

    with pytest.raises(errors.InternalDefect) as raised:
        runner.run(plan, ports=ports)

    assert "preflight" in str(raised.value).lower()


def test_a_well_behaved_stage_passes_preflight(ports: portset.HostPorts) -> None:
    plan = plans.Plan.of("demo", [acting_stage("apply")])

    assert runner.run(plan, ports=ports).succeeded


def test_the_ports_a_stage_sees_during_apply_are_the_real_bundle(
    ports: portset.HostPorts,
) -> None:
    seen: list[object] = []

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        seen.append(context.ports.processes)
        return stages.Advance(facts={TOKEN: "value"})

    plan = plans.Plan.of(
        "demo",
        [
            stages.SimpleStage(
                id=identifiers.StageId("only"),
                reads=(),
                writes=(TOKEN,),
                attests=frozenset(),
                effects=frozenset(),
                preflight=lambda context: stages.Ready(),
                apply=apply,
            )
        ],
    )

    runner.run(plan, ports=ports)

    assert seen == [ports.processes]


def test_the_planning_bundle_has_the_shape_of_the_real_one(ports: portset.HostPorts) -> None:
    planning = ports.for_planning()

    assert type(planning) is type(ports)
    for call in (
        lambda: planning.files.exists(None),  # type: ignore[arg-type]
        lambda: planning.clock.now(),
        lambda: planning.identities.run_id(),
        lambda: planning.archives.bundle(None, into=None),  # type: ignore[arg-type]
    ):
        with pytest.raises(errors.InternalDefect):
            call()

"""The runner: preflight everything, then apply, then unwind in reverse."""

from __future__ import annotations

import dataclasses

from apex.kernel import identifiers, refusals
from apex.pipeline import effects, facts, plans, runner, stages
from apex.ports import portset

TOKEN = facts.FactKey[str]("token")
ARTIFACT = facts.FactKey[str]("artifact")
REPORT = facts.FactKey[str]("report")


@dataclasses.dataclass
class Recorder:
    events: list[str] = dataclasses.field(default_factory=list)


def stage(
    name: str,
    *,
    reads: tuple[facts.FactKey, ...] = (),
    writes: tuple[facts.FactKey, ...] = (),
    log: Recorder,
    preflight: stages.Preflight | None = None,
    outcome: str = "advance",
    attests: frozenset[str] = frozenset(),
    acquires: bool = False,
) -> stages.Stage[portset.HostPorts]:
    def run_preflight(context: object) -> stages.Preflight:
        log.events.append(f"preflight:{name}")
        return preflight or stages.Ready()

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        log.events.append(f"apply:{name}")
        finaliser = None
        if acquires:
            def release() -> None:
                log.events.append(f"release:{name}")

            finaliser = stages.Finaliser(name=f"release {name}", release=release)
        if outcome == "refuse":
            return stages.Refuse(refusals.RefusalReason.LOCK_HELD, detail=name)
        produced = dict.fromkeys(writes, name)
        return stages.Advance(facts=produced, finaliser=finaliser)

    return stages.SimpleStage(
        id=identifiers.StageId(name),
        reads=reads,
        writes=writes,
        attests=frozenset(identifiers.CheckId(item) for item in attests),
        effects=frozenset({effects.Effect.READS_HOST}),
        preflight=run_preflight,
        apply=apply,
    )


def test_every_stage_is_preflighted_before_any_stage_applies(ports: portset.HostPorts) -> None:
    log = Recorder()
    plan = plans.Plan.of(
        "demo",
        [
            stage("second", reads=(TOKEN,), writes=(ARTIFACT,), log=log),
            stage("first", writes=(TOKEN,), log=log),
        ],
    )

    runner.run(plan, ports=ports)

    preflights = [item for item in log.events if item.startswith("preflight:")]
    applies = [item for item in log.events if item.startswith("apply:")]
    assert log.events.index(applies[0]) > log.events.index(preflights[-1])


def test_a_refusal_at_preflight_means_nothing_is_applied(ports: portset.HostPorts) -> None:
    log = Recorder()
    plan = plans.Plan.of(
        "demo",
        [
            stage("first", writes=(TOKEN,), log=log),
            stage(
                "second",
                reads=(TOKEN,),
                writes=(ARTIFACT,),
                log=log,
                preflight=stages.RefuseBecause(refusals.RefusalReason.LOCK_HELD, "held"),
            ),
        ],
    )

    outcome = runner.run(plan, ports=ports)

    assert not outcome.succeeded
    assert not [item for item in log.events if item.startswith("apply:")]


def test_the_derived_order_follows_the_data_not_the_listing() -> None:
    log = Recorder()
    plan = plans.Plan.of(
        "demo",
        [
            stage("collect", reads=(ARTIFACT,), writes=(REPORT,), log=log),
            stage("acquire", writes=(TOKEN,), log=log),
            stage("build", reads=(TOKEN,), writes=(ARTIFACT,), log=log),
        ],
    )

    assert [str(item) for item in plan.order] == ["acquire", "build", "collect"]


def test_finalisers_unwind_in_reverse_order_of_acquisition(ports: portset.HostPorts) -> None:
    log = Recorder()
    plan = plans.Plan.of(
        "demo",
        [
            stage("outer", writes=(TOKEN,), log=log, acquires=True),
            stage("inner", reads=(TOKEN,), writes=(ARTIFACT,), log=log, acquires=True),
        ],
    )

    runner.run(plan, ports=ports)

    releases = [item for item in log.events if item.startswith("release:")]
    assert releases == ["release:inner", "release:outer"]


def test_a_refusal_part_way_through_still_unwinds_what_was_acquired(
    ports: portset.HostPorts,
) -> None:
    log = Recorder()
    plan = plans.Plan.of(
        "demo",
        [
            stage("acquire", writes=(TOKEN,), log=log, acquires=True),
            stage("fail", reads=(TOKEN,), writes=(ARTIFACT,), log=log, outcome="refuse"),
        ],
    )

    outcome = runner.run(plan, ports=ports)

    assert not outcome.succeeded
    assert "release:acquire" in log.events


def test_a_run_that_stops_records_not_tested_for_every_unreached_check(
    ports: portset.HostPorts,
) -> None:
    log = Recorder()
    plan = plans.Plan.of(
        "demo",
        [
            stage("fail", writes=(TOKEN,), log=log, outcome="refuse"),
            stage("later", reads=(TOKEN,), writes=(ARTIFACT,), log=log, attests={"image.lint"}),
        ],
    )

    outcome = runner.run(plan, ports=ports)

    assert [str(item) for item in outcome.not_tested] == ["image.lint"]


def test_a_successful_run_reports_the_facts_it_produced(ports: portset.HostPorts) -> None:
    log = Recorder()
    plan = plans.Plan.of("demo", [stage("only", writes=(TOKEN,), log=log)])

    outcome = runner.run(plan, ports=ports)

    assert outcome.succeeded
    assert outcome.facts[TOKEN] == "only"


def test_the_plan_digest_is_stable_for_the_same_stage_set() -> None:
    log = Recorder()
    first = plans.Plan.of("demo", [stage("a", writes=(TOKEN,), log=log)])
    second = plans.Plan.of("demo", [stage("a", writes=(TOKEN,), log=log)])

    assert first.digest == second.digest


def test_the_plan_digest_changes_when_a_stage_is_added() -> None:
    log = Recorder()
    first = plans.Plan.of("demo", [stage("a", writes=(TOKEN,), log=log)])
    second = plans.Plan.of(
        "demo",
        [
            stage("a", writes=(TOKEN,), log=log),
            stage("b", reads=(TOKEN,), writes=(ARTIFACT,), log=log),
        ],
    )

    assert first.digest != second.digest

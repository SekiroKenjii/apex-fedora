"""Prepare the Ventoy medium in the builder from inputs the host has proven, and bind it.

The builder proves itself, the agent is delivered, every input is accepted on the host and
the request written, the work directory is laid out in the builder, the fixture unit runs
over it, the medium comes home and is accepted only against the report, and the report is
retained beside it. Booting the medium is a separate check, NOT TESTED here.
"""

from __future__ import annotations

from apex.composition import keys as composition_keys
from apex.composition.stages import identify_run_stage
from apex.kernel import identifiers, safepaths
from apex.pipeline import plans, runner, stages
from apex.ports import guestshell, portset
from apex.verification import probes, ventoymedia, verifykeys
from apex.verification.stages import (
    builder_guard_stage,
    deliver_agent_stage,
    probe_stage,
    retain_report_stage,
    ventoy_inputs_stage,
    ventoy_retrieve_stage,
    ventoy_work_stage,
)

NAME = "build-ventoy-media"
CASE = probes.lookup(identifiers.ProbeId("fixture.ventoy"))


def _arguments(context: stages.RunContext[portset.HostPorts]) -> dict[str, str]:
    return {"work": str(context.facts[verifykeys.WORK])}


STAGES = (
    identify_run_stage.STAGE,
    builder_guard_stage.STAGE,
    deliver_agent_stage.STAGE,
    ventoy_inputs_stage.STAGE,
    ventoy_work_stage.STAGE,
    probe_stage.for_case(CASE, arguments=_arguments, after=(verifykeys.WORK,)),
    ventoy_retrieve_stage.for_case(CASE),
    retain_report_stage.for_probe(CASE),
)
SEEDS = frozenset(
    {
        verifykeys.BUILDER,
        verifykeys.WHEEL,
        verifykeys.VENTOY_INPUTS,
        composition_keys.RUNTIME_ROOT,
        composition_keys.REPOSITORY,
    }
)
PLAN: plans.Plan[portset.HostPorts] = plans.Plan.of(NAME, STAGES, seeds=SEEDS)


def prepare(  # noqa: PLR0913
    ports: portset.HostPorts,
    *,
    builder: guestshell.GuestTarget,
    wheel: safepaths.SafePath,
    root: safepaths.RuntimeRoot,
    repository: safepaths.SourceRoot,
    inputs: ventoymedia.Inputs,
) -> runner.Outcome:
    return runner.run(
        PLAN,
        ports=ports,
        seeds={
            verifykeys.BUILDER: builder,
            verifykeys.WHEEL: wheel,
            verifykeys.VENTOY_INPUTS: inputs,
            composition_keys.RUNTIME_ROOT: root,
            composition_keys.REPOSITORY: repository,
        },
    )

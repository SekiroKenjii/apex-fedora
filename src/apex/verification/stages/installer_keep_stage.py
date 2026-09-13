"""Keep the guest's fault report beside the machine's run, where the collection reads it."""

from __future__ import annotations

from apex.kernel import identifiers
from apex.pipeline import effects, stages
from apex.ports import portset
from apex.verification import faulting, installerfault, judging, verifykeys


def for_case(case: faulting.FaultCase) -> stages.SimpleStage[portset.HostPorts]:
    report = verifykeys.fault_report(case)

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        found = context.facts[report]
        kept = installerfault.write_kept(
            context.ports,
            context.facts[verifykeys.MACHINE_RUN],
            request=context.facts[verifykeys.INSTALLER_REQUEST],
            observations={**found.observations, judging.VERDICT: found.verdict.stored_name},
        )
        return stages.Advance(facts={verifykeys.KEPT: kept})

    return stages.SimpleStage(
        id=identifiers.StageId("installer.keep"),
        reads=(report, verifykeys.INSTALLER_REQUEST, verifykeys.MACHINE_RUN),
        writes=(verifykeys.KEPT,),
        attests=frozenset(),
        effects=frozenset({effects.Effect.WRITES_RUNTIME}),
        preflight=stages.always_ready,
        apply=apply,
    )

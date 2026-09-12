"""Record one check's verdict from the reports that establish it.

One record per check, whatever the number of reports behind it, because the readiness fold
refuses a check with two records. The verdict is the meet of the reports' verdicts, and every
report is filed as proof with whatever it captured beside it. The preflight refuses a
witness the check cannot accept before any guest is asked, so a run that could never be
recorded never mutates a guest.
"""

from __future__ import annotations

from collections.abc import Sequence

from apex.attestation import catalogue
from apex.kernel import claims, errors, identifiers, refusals, verdicts
from apex.pipeline import effects, facts, stages
from apex.ports import portset
from apex.verification import judging, verifykeys


def for_check[E: judging.Evidence](
    check: identifiers.CheckId, *, reports: Sequence[facts.FactKey[E]]
) -> stages.SimpleStage[portset.HostPorts]:
    key = verifykeys.minted(check)

    def preflight(context: stages.RunContext[portset.HostPorts]) -> stages.Preflight:
        required = catalogue.specification(check).environment
        witness = context.facts[verifykeys.WITNESS]
        if not witness.satisfies(required):
            return stages.RefuseBecause(
                reason=refusals.RefusalReason.ENVIRONMENT_NOT_WITNESSED,
                detail=f"{check} needs {required}; the guest is declared {witness}",
            )
        return stages.Ready()

    def apply(context: stages.RunContext[portset.HostPorts]) -> stages.StageResult:
        found = [context.facts[report] for report in reports]
        verdict = verdicts.fold(
            (item.verdict for item in found), reason=refusals.RefusalReason.NO_VERIFIED_RESULT
        )
        try:
            recorded = context.facts[verifykeys.RECORDER].record(
                check=check,
                verdict=verdict,
                offered=[proof for item in found for proof in (item.proof, *item.extras)],
                candidate=context.facts[verifykeys.CANDIDATE],
                witnessed=claims.witnessed_through(
                    context.ports.environment, context.facts[verifykeys.WITNESS]
                ),
            )
        except errors.Refusal as refusal:
            return stages.Refuse(reason=refusal.reason, detail=refusal.subject)
        return stages.Advance(facts={key: recorded})

    return stages.SimpleStage(
        id=identifiers.StageId(f"attest.{check}"),
        reads=(*reports, verifykeys.WITNESS, verifykeys.CANDIDATE, verifykeys.RECORDER),
        writes=(key,),
        attests=frozenset({check}),
        effects=frozenset({effects.Effect.EMITS_EVIDENCE, effects.Effect.WRITES_RUNTIME}),
        preflight=preflight,
        apply=apply,
    )

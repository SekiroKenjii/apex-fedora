"""Proving the verifier refuses what it must, on a copy of a bundle it accepts.

A verifier that accepts an altered bundle is worse than none, because it produces a passing
result that means nothing. The exercise therefore fails the run if any registered negative
is accepted, or refused for a reason other than the one it declares.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from apex.kernel import errors, refusals
from apex.ports import portset
from apex.trust import negatives, verifying


@dataclasses.dataclass(frozen=True, slots=True)
class ExerciseReport:
    accepted: verifying.VerifiedBundle
    refused: Mapping[str, refusals.RefusalReason]


def exercise(
    ports: portset.HostPorts,
    *,
    trial: negatives.Trial,
    scratch: verifying.BundleLocation,
) -> ExerciseReport:
    accepted = verifying.verify_bundle(ports, location=trial.location, anchor=trial.anchor)
    refused: dict[str, refusals.RefusalReason] = {}
    for negative in negatives.registered():
        case = verifying.BundleLocation(
            root=scratch.root, relative=f"{scratch.relative}/{negative.id}"
        )
        prepared = negative.prepare(ports, original=trial, scratch=case)
        refused[str(negative.id)] = _observe(ports, negative, prepared)
    return ExerciseReport(accepted=accepted, refused=refused)


def _observe(
    ports: portset.HostPorts, negative: negatives.Negative, prepared: negatives.Trial
) -> refusals.RefusalReason:
    try:
        verifying.verify_bundle(ports, location=prepared.location, anchor=prepared.anchor)
    except errors.Refusal as refusal:
        if refusal.reason is not negative.expects:
            raise errors.Refusal(
                refusals.RefusalReason.NEGATIVE_WRONG_REASON,
                subject=f"{negative.id}: refused as {refusal.reason.value}",
                remedy=f"the verifier should have refused as {negative.expects.value}",
            ) from refusal
        return refusal.reason
    raise errors.Refusal(
        refusals.RefusalReason.NEGATIVE_ACCEPTED,
        subject=str(negative.id),
        remedy="the verifier accepted a bundle it must refuse; do not trust its passes",
    )

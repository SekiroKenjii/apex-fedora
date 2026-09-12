"""A deliberate breakage a guest is asked to attempt, and what its report is worth.

A fault case names the guest unit and where the guest must be standing. The unit reports a
status the older scripts spelt the same way; the host turns it into a verdict and keeps the
whole report as the proof the verdict cites. The isolated builder is a guest like any test
machine, so a case may stand in the build environment; only a simulation and the operator's
own machine are not places a guest can be asked to break something.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from apex.attestation import minting
from apex.kernel import claims, encoding, errors, identifiers, verdicts

REPORT_KIND = ".json"
STATUS = "status"
NOT_A_GUEST = frozenset({claims.EnvironmentKind.SIMULATED, claims.EnvironmentKind.OPERATOR})


@dataclasses.dataclass(frozen=True, slots=True)
class FaultCase:
    unit: identifiers.ProbeId
    environment: claims.EnvironmentKind
    summary: str
    arguments: Mapping[str, encoding.JsonValue] = dataclasses.field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.environment in NOT_A_GUEST:
            raise errors.RegistrationError(
                f"{self.unit}: a fault is attempted in a guest, and {self.environment} is not one"
            )
        if not self.summary:
            raise errors.RegistrationError(f"{self.unit}: say what the fault attempts")


@dataclasses.dataclass(frozen=True, slots=True)
class FaultReport:
    case: FaultCase
    observations: encoding.Document
    verdict: verdicts.Verdict
    proof: minting.Offered
    extras: tuple[minting.Offered, ...] = ()


def judge(observations: encoding.Document) -> verdicts.Verdict:
    """The report's own status, and BLOCKED for a report that does not state one.

    A missing or unknown status is never a failure, because a failure says the product did
    the wrong thing, and never a pass; it is a fault in the run that blocks the verdict.
    """
    status = observations.get(STATUS)
    if status == verdicts.Passed.stored_name:
        return verdicts.PASSED
    if status == verdicts.Failed.stored_name:
        return verdicts.FAILED
    return verdicts.BLOCKED


def report(
    case: FaultCase, observations: encoding.Document, *, reply: encoding.Document
) -> FaultReport:
    return FaultReport(
        case=case,
        observations=observations,
        verdict=judge(observations),
        proof=minting.Offered(payload=encoding.canonical(reply), kind=REPORT_KIND),
    )

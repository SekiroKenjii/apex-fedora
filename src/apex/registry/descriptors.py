"""Frozen declarations. A unit says what it is; it does not do anything."""

from __future__ import annotations

import dataclasses

from apex.kernel import claims, errors, identifiers, refusals

HARDWARE_GROUP = "hardware"


@dataclasses.dataclass(frozen=True, slots=True)
class CheckSpec:
    id: identifiers.CheckId
    group: str
    environment: claims.EnvironmentKind
    summary: str

    def __post_init__(self) -> None:
        if not self.summary:
            raise errors.Refusal(
                refusals.RefusalReason.UNKNOWN_CHECK,
                subject=str(self.id),
                remedy="say what the check establishes",
            )
        if self.environment is claims.EnvironmentKind.SIMULATED:
            raise errors.Refusal(
                refusals.RefusalReason.SIMULATED_ENVIRONMENT,
                subject=str(self.id),
                remedy="a check cannot be satisfied by a simulated run",
            )
        if self.group == HARDWARE_GROUP and self.environment is not claims.EnvironmentKind.PHYSICAL:
            raise errors.Refusal(
                refusals.RefusalReason.HARDWARE_REQUIRES_PHYSICAL,
                subject=str(self.id),
                remedy="hardware evidence comes from the machine, never from a virtual one",
            )

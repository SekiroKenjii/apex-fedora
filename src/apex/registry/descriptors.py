"""Frozen declarations. A unit says what it is; it does not do anything."""

from __future__ import annotations

import dataclasses

from apex.kernel import claims, errors, identifiers, refusals

HARDWARE_GROUP = "hardware"


PERMITTED_PROOF_KINDS = frozenset({".txt", ".log", ".json", ".png", ".ppm", ".xml"})


@dataclasses.dataclass(frozen=True, slots=True)
class CheckSpec:
    id: identifiers.CheckId
    group: str
    environment: claims.EnvironmentKind
    summary: str
    accepted_proof_kinds: tuple[str, ...] = ()
    scope_limits: tuple[str, ...] = ()
    sourced_from: str = ""

    def __post_init__(self) -> None:
        unknown = set(self.accepted_proof_kinds) - PERMITTED_PROOF_KINDS
        if unknown:
            raise errors.Refusal(
                refusals.RefusalReason.PROOF_KIND_NOT_ACCEPTED,
                subject=f"{self.id}: {', '.join(sorted(unknown))}",
                remedy="a proof is text, JSON, an image or a JUnit report, never a template",
            )
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

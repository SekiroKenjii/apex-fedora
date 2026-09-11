"""Frozen declarations. A unit says what it is; it does not do anything.

A declaration that contradicts itself is a fault in the unit, found before anything runs, so
it is a `RegistrationError` and never a refusal aimed at the operator.
"""

from __future__ import annotations

import dataclasses

from apex.kernel import claims, errors, identifiers

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
            raise errors.RegistrationError(
                f"{self.id}: proof kinds {', '.join(sorted(unknown))} are not permitted; "
                "a proof is text, JSON, an image or a JUnit report, never a template"
            )
        if not self.summary:
            raise errors.RegistrationError(f"{self.id}: say what the check establishes")
        if self.environment is claims.EnvironmentKind.SIMULATED:
            raise errors.RegistrationError(
                f"{self.id}: a check cannot be satisfied by a simulated run"
            )
        if self.group == HARDWARE_GROUP and self.environment is not claims.EnvironmentKind.PHYSICAL:
            raise errors.RegistrationError(
                f"{self.id}: hardware evidence comes from the machine, never from a virtual one"
            )

"""What a result asserts, and what it deliberately does not.

The environment is proven by whichever adapter executed, never by an argument, so a
simulated run cannot describe itself as physical.
"""

from __future__ import annotations

import dataclasses
import enum
from collections.abc import Iterable

from apex.kernel import errors, refusals


class EnvironmentKind(enum.StrEnum):
    BUILD = "build"
    BUILD_CONTAINER = "build-container"
    VM = "vm"
    LIVE_VM = "live-vm"
    INSTALLER_VM = "installer-vm"
    PHYSICAL = "physical"
    OPERATOR = "operator"
    SIMULATED = "simulated"

    def satisfies(self, required: EnvironmentKind) -> bool:
        if self is EnvironmentKind.SIMULATED:
            return False
        return self is required


def meet(kinds: Iterable[EnvironmentKind]) -> EnvironmentKind:
    """The weakest environment in a bundle. Simulation dominates everything."""
    observed = list(kinds)
    if not observed or any(kind is EnvironmentKind.SIMULATED for kind in observed):
        return EnvironmentKind.SIMULATED
    first = observed[0]
    if any(kind is not first for kind in observed):
        raise errors.InternalDefect(f"a bundle mixes environments: {sorted(set(observed))}")
    return first


class ScopeLimit(enum.StrEnum):
    PHYSICAL_HARDWARE = "physical-hardware"
    FAILED_DEPLOYMENT_RECOVERY = "failed-deployment-recovery"
    SECURE_BOOT = "secure-boot"
    UPSTREAM_PROSE_UNVERIFIED = "upstream-prose-unverified"
    LEGACY_NO_PORT_PROOF = "legacy-no-port-proof"
    LEGACY_NO_CANDIDATE_READBACK = "legacy-no-candidate-readback"


@dataclasses.dataclass(frozen=True, slots=True)
class ClaimScope:
    proven: frozenset[str]
    not_tested: frozenset[ScopeLimit]

    def __post_init__(self) -> None:
        if not self.proven and not self.not_tested:
            raise errors.Refusal(
                refusals.RefusalReason.NO_VERIFIED_RESULT,
                subject="ClaimScope",
                remedy="state what was proven or what remains untested",
            )


@dataclasses.dataclass(frozen=True, slots=True)
class Claim:
    statement: str
    environment: EnvironmentKind
    scope: ClaimScope

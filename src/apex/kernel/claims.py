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


def witnessed_through(bundle: EnvironmentKind, guest: EnvironmentKind) -> EnvironmentKind:
    """The environment a guest's answer stands in, seen through the host bundle that asked.

    A fake anywhere in the bundle makes the answer simulated whatever the guest was. A real
    bundle witnesses what the adapter that launched the guest declared for it, because the
    host's own adapters only ever run on the host and cannot vouch for a machine.
    """
    if bundle is EnvironmentKind.SIMULATED or guest is EnvironmentKind.SIMULATED:
        return EnvironmentKind.SIMULATED
    return guest


ATTESTABLE = frozenset(
    kind for kind in EnvironmentKind if kind is not EnvironmentKind.SIMULATED
)


def require_attestable(
    kind: EnvironmentKind, *, expected: EnvironmentKind | None = None
) -> EnvironmentKind:
    """Refuse anything not on the allowlist, and anything that is not what was asked for."""
    if kind not in ATTESTABLE:
        raise errors.Refusal(
            refusals.RefusalReason.SIMULATED_ENVIRONMENT,
            subject=str(kind),
            remedy="only a bundle of real adapters may authorise a recorded result",
        )
    if expected is not None and kind is not expected:
        raise errors.Refusal(
            refusals.RefusalReason.ENVIRONMENT_NOT_WITNESSED,
            subject=f"the bundle witnesses {kind}, not {expected}",
            remedy="run the check through ports that execute in the environment it requires",
        )
    return kind


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

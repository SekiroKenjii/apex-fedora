"""The authority a stage holds over the outside world, bundled.

A stage receives one of these and nothing else. The environment it may attest to is the
weakest of its members, so a single fake anywhere makes the whole bundle unable to authorise
a result.
"""

from __future__ import annotations

import dataclasses

from apex.kernel import claims, errors, refusals
from apex.ports import clock, files, ids, process


@dataclasses.dataclass(frozen=True, slots=True)
class HostPorts:
    processes: process.ProcessPort
    files: files.FileSystemPort
    clock: clock.ClockPort
    identities: ids.IdentityPort

    @property
    def environment(self) -> claims.EnvironmentKind:
        return claims.meet(
            member.environment
            for member in (self.processes, self.files, self.clock, self.identities)
        )

    def require_attestable(self) -> claims.EnvironmentKind:
        """Refuse to let a simulated bundle authorise a recorded result."""
        kind = self.environment
        if kind is claims.EnvironmentKind.SIMULATED:
            raise errors.Refusal(
                refusals.RefusalReason.SIMULATED_ENVIRONMENT,
                subject="a bundle holding a fake adapter",
                remedy="only a bundle of real adapters may authorise a recorded result",
            )
        return kind

"""The authority a stage holds over the outside world, bundled.

A stage receives one of these and nothing else. The environment it may attest to is the
weakest of its members, so a single fake anywhere makes the whole bundle unable to authorise
a result.
"""

from __future__ import annotations

import dataclasses

from apex.kernel import claims
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

    def require_attestable(
        self, *, expected: claims.EnvironmentKind | None = None
    ) -> claims.EnvironmentKind:
        """Refuse unless this bundle witnesses an environment on the allowlist.

        Every adapter here runs on the host, so this bundle can only ever witness a build
        environment. Asking it to prove a virtual machine or a physical laptop is refused
        rather than answered, because a class attribute is a declaration and not a proof.
        """
        return claims.require_attestable(self.environment, expected=expected)

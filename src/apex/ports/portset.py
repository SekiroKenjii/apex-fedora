"""The authority a stage holds over the outside world, bundled.

A stage receives one of these and nothing else. The environment it may attest to is the
weakest of its members, so a single fake anywhere makes the whole bundle unable to authorise
a result. The same bundle shape, with every member refusing, is what a stage holds while it
plans, so planning cannot reach anything apply could not.
"""

from __future__ import annotations

import dataclasses
from typing import Protocol, Self

from apex.kernel import claims
from apex.ports import (
    archives,
    clock,
    digesting,
    downloading,
    files,
    hypervisor,
    ids,
    locking,
    planning,
    process,
    qmp,
    signing,
)


class PortBundle(Protocol):
    @property
    def environment(self) -> claims.EnvironmentKind: ...

    def for_planning(self) -> Self: ...


@dataclasses.dataclass(frozen=True, slots=True)
class HostPorts:
    processes: process.ProcessPort
    files: files.FileSystemPort
    clock: clock.ClockPort
    identities: ids.IdentityPort
    locks: locking.LockPort
    digests: digesting.DigestPort
    archives: archives.ArchivePort
    signing: signing.SigningPort
    downloads: downloading.DownloadPort
    hypervisor: hypervisor.HypervisorPort
    monitor: qmp.QmpPort

    @property
    def environment(self) -> claims.EnvironmentKind:
        return claims.meet(
            member.environment
            for member in (
                self.processes,
                self.files,
                self.clock,
                self.identities,
                self.locks,
                self.digests,
                self.archives,
                self.signing,
                self.downloads,
                self.hypervisor,
                self.monitor,
            )
        )

    def for_planning(self) -> Self:
        return type(self)(
            processes=planning.Refusing("processes"),
            files=planning.Refusing("files"),
            clock=planning.Refusing("clock"),
            identities=planning.Refusing("identities"),
            locks=planning.Refusing("locks"),
            digests=planning.Refusing("digests"),
            archives=planning.Refusing("archives"),
            signing=planning.Refusing("signing"),
            downloads=planning.Refusing("downloads"),
            hypervisor=planning.Refusing("hypervisor"),
            monitor=planning.Refusing("monitor"),
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

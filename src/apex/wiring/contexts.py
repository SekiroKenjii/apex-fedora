"""What the root hands every command: the settings, the roots, the environment, the ports.

The bundle is a callable rather than a value because a command that only plans must not
pay for a runtime root it never reads, and one that reads the store obtains real ports for
exactly the root it was given. The serial shell is a second callable, for the one guest
that has no ssh: a context built without one refuses to open a console rather than
opening the wrong thing.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping

from apex.config import loader
from apex.kernel import errors, refusals, safepaths
from apex.ports import guestshell, portset

Bundle = Callable[[safepaths.RuntimeRoot], portset.HostPorts]
SerialShell = Callable[[safepaths.SafePath, int], guestshell.GuestShellPort]


def unwired_serial(socket_path: safepaths.SafePath, process: int) -> guestshell.GuestShellPort:
    raise errors.PreconditionUnmet(
        refusals.RefusalReason.TOPOLOGY_INCONSISTENT,
        subject=f"no serial shell is wired for {socket_path} (process {process})",
    )


@dataclasses.dataclass(frozen=True, slots=True)
class Context:
    settings: loader.Settings
    repository: safepaths.SourceRoot
    root: safepaths.RuntimeRoot | None
    environment: Mapping[str, str]
    bundle: Bundle
    serial: SerialShell = unwired_serial

"""What the root hands every command: the settings, the roots, the environment, the ports.

The bundle is a callable rather than a value because a command that only plans must not
pay for a runtime root it never reads, and one that reads the store obtains real ports for
exactly the root it was given.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping

from apex.config import loader
from apex.kernel import safepaths
from apex.ports import portset

Bundle = Callable[[safepaths.RuntimeRoot], portset.HostPorts]


@dataclasses.dataclass(frozen=True, slots=True)
class Context:
    settings: loader.Settings
    repository: safepaths.SourceRoot
    root: safepaths.RuntimeRoot | None
    environment: Mapping[str, str]
    bundle: Bundle

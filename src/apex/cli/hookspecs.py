"""What a hook kind is, separately from which ones exist.

The renderer is told the noun to read back rather than anything about git, so transferring a
second hook adds a file and teaches the renderer nothing.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from apex.workspace import rulespecs


@dataclasses.dataclass(frozen=True, slots=True)
class HookRequest:
    repository: Path
    arguments: Sequence[str]
    standard_input: str


class InspectHook(Protocol):
    def __call__(self, request: HookRequest) -> Sequence[rulespecs.Finding]: ...


@dataclasses.dataclass(frozen=True, slots=True)
class HookKind:
    name: str
    subject: str
    inspect: InspectHook

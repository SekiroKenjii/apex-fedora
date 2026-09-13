"""What a hook kind is, separately from which ones exist.

The renderer is told the noun to read back rather than anything about git, so transferring a
second hook adds a file and teaches the renderer nothing. A hook that reads the repository
does so through the process port the request carries, never by running git itself.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from apex.ports import process
from apex.workspace import rulespecs


@dataclasses.dataclass(frozen=True, slots=True)
class HookRequest:
    repository: Path
    arguments: Sequence[str]
    standard_input: str
    processes: process.ProcessPort


class InspectHook(Protocol):
    def __call__(self, request: HookRequest) -> Sequence[rulespecs.Finding]: ...


@dataclasses.dataclass(frozen=True, slots=True)
class HookKind:
    name: str
    subject: str
    remedy: str
    inspect: InspectHook

    @property
    def footer(self) -> str:
        return f"If this refusal is wrong, the rule that refused is named above; {self.remedy}."

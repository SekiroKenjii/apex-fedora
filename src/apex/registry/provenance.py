"""Where a registered unit came from.

Without this, a registry trades an editable central list for invisible behaviour. With it,
adding a unit stays a reviewable diff and a duplicate names both places it came from.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True, slots=True)
class Provenance:
    module: str
    qualname: str
    line: int

    def __str__(self) -> str:
        return f"{self.module}.{self.qualname} at line {self.line}"

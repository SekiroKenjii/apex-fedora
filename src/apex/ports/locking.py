"""Named exclusion scopes with an explicit acquisition policy.

The current code holds two incompatible behaviours under one name: the machine lock blocks
until the holder goes away, and the remote build lock refuses at once. Neither records who
holds it, so a refusal cannot say.
"""

from __future__ import annotations

import contextlib
import dataclasses
from typing import Protocol, Self

from apex.kernel import claims, timing


@dataclasses.dataclass(frozen=True, slots=True)
class LockScope:
    name: str


@dataclasses.dataclass(frozen=True, slots=True)
class AcquisitionPolicy:
    budget: timing.Elapsed | None

    @classmethod
    def immediate(cls) -> Self:
        return cls(budget=None)

    @classmethod
    def wait(cls, budget: timing.Elapsed) -> Self:
        return cls(budget=budget)


@dataclasses.dataclass(frozen=True, slots=True)
class LockLease:
    scope: LockScope
    holder: str


class LockPort(Protocol):
    environment: claims.EnvironmentKind

    def acquire(
        self, scope: LockScope, policy: AcquisitionPolicy
    ) -> contextlib.AbstractContextManager[LockLease]: ...

    def holder(self, scope: LockScope) -> str | None: ...

"""Named exclusion scopes with an explicit acquisition policy.

Whether an acquisition waits or refuses at once is a value the caller passes, never a property
of the scope. Every lease records its holder, so a refusal can name who holds the scope.
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

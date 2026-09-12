"""In-memory exclusion with the same refusal behaviour as the real lock."""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from apex.kernel import claims, errors, refusals
from apex.ports import locking


class MemoryLocks(locking.LockPort):
    environment = claims.EnvironmentKind.SIMULATED

    def __init__(self) -> None:
        self._held: dict[str, str] = {}
        self._issued = 0
        self.waits: list[locking.AcquisitionPolicy] = []

    def holder(self, scope: locking.LockScope) -> str | None:
        return self._held.get(scope.name)

    @contextlib.contextmanager
    def acquire(
        self, scope: locking.LockScope, policy: locking.AcquisitionPolicy
    ) -> Iterator[locking.LockLease]:
        current = self._held.get(scope.name)
        if current is not None:
            # Nothing releases a lock in memory, so a bounded wait can only end in refusal.
            # Recording it keeps the policy observable to a test.
            self.waits.append(policy)
            raise errors.Refusal(
                refusals.RefusalReason.LOCK_HELD,
                subject=f"{scope.name} is held by {current}",
                remedy="wait for the holder to finish or stop it",
            )
        self._issued += 1
        identity = f"holder {self._issued}"
        self._held[scope.name] = identity
        try:
            yield locking.LockLease(scope=scope, holder=identity)
        finally:
            self._held.pop(scope.name, None)

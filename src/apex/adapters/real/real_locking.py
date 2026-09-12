"""File locks that write the holder, so a refusal can name it."""

from __future__ import annotations

import contextlib
import fcntl
import os
import time
from collections.abc import Iterator
from typing import IO

from apex.kernel import claims, errors, refusals, safepaths
from apex.ports import locking

POLL = 0.01


class FileLocks(locking.LockPort):
    environment = claims.EnvironmentKind.BUILD

    def __init__(self, root: safepaths.RuntimeRoot) -> None:
        self._root = root

    def _path(self, scope: locking.LockScope) -> safepaths.SafePath:
        return self._root.child(f"{scope.name}.lock")

    def holder(self, scope: locking.LockScope) -> str | None:
        path = self._path(scope).path
        if not path.is_file():
            return None
        recorded = path.read_text().strip()
        return recorded or None

    @contextlib.contextmanager
    def acquire(
        self, scope: locking.LockScope, policy: locking.AcquisitionPolicy
    ) -> Iterator[locking.LockLease]:
        path = self._path(scope).path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = path.open("a+")
        taken = False
        try:
            self._take(handle, scope, policy)
            taken = True
            identity = f"process {os.getpid()}"
            handle.seek(0)
            handle.truncate()
            handle.write(identity)
            handle.flush()
            yield locking.LockLease(scope=scope, holder=identity)
        finally:
            # The lock is advisory, so a process that only opened the file can still truncate
            # it. Clearing the record on the path where nothing was taken erases the identity
            # the real holder wrote, and every refusal after the first stops naming anyone.
            if taken:
                with contextlib.suppress(OSError):
                    handle.seek(0)
                    handle.truncate()
                    handle.flush()
                    fcntl.flock(handle, fcntl.LOCK_UN)
            handle.close()

    def _take(
        self, handle: IO[str], scope: locking.LockScope, policy: locking.AcquisitionPolicy
    ) -> None:
        deadline = None if policy.budget is None else time.monotonic() + policy.budget.seconds
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError as error:
                if deadline is None or time.monotonic() >= deadline:
                    raise errors.Refusal(
                        refusals.RefusalReason.LOCK_HELD,
                        subject=(
                            f"{scope.name} is held by "
                            f"{self.holder(scope) or 'another process'}"
                        ),
                        remedy="wait for the holder to finish or stop it",
                    ) from error
                time.sleep(POLL)

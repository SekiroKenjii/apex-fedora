"""A registry of cases discovered from one package, sealed on first use, looked up by name.

Every catalogue of the same shape, the guest's units, the host's probes and faults, the
checks, is one of these: a module under the package declares a case at import, discovery
imports every module once, and a name nobody declared is refused with the names that exist.
"""

from __future__ import annotations

from collections.abc import Callable

from apex.kernel import errors, refusals
from apex.registry import decorators, discovery, registry


class Casebook[C]:
    def __init__(self, *, kind: str, namespace: str, key: Callable[[C], str], known: str) -> None:
        self._collector: registry.Registry[str, C] = registry.Registry(kind)
        self._sealed: registry.SealedRegistry[str, C] | None = None
        self._namespace = namespace
        self._key = key
        self._known = known

    def declare(self, case: C) -> C:
        self._collector.add(self._key(case), case, at=decorators.caller(3))
        return case

    def sealed(self) -> registry.SealedRegistry[str, C]:
        if self._sealed is None:
            discovery.discover([self._namespace])
            self._sealed = self._collector.seal()
        return self._sealed

    def registered(self) -> tuple[C, ...]:
        return tuple(case for _, case in sorted(self.sealed().items(), key=lambda item: item[0]))

    def lookup(self, name: object) -> C:
        if str(name) not in self.sealed():
            raise errors.Refusal(
                refusals.RefusalReason.UNIT_UNKNOWN,
                subject=str(name),
                remedy=f"{self._known}: {', '.join(sorted(self.sealed()))}",
            )
        return self.sealed().lookup(str(name))

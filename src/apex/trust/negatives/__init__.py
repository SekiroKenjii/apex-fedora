"""The refusals a verifier must make, one module each.

This module never names a negative. Dropping a file into this directory registers one, and
the exercise runs every registered negative, so a new way to tamper with a bundle becomes a
required refusal the moment it is declared.
"""

from __future__ import annotations

import dataclasses
from typing import Protocol

from apex.kernel import identifiers, refusals
from apex.ports import portset
from apex.registry import decorators, discovery, registry
from apex.trust import anchors, verifying


@dataclasses.dataclass(frozen=True, slots=True)
class Trial:
    location: verifying.BundleLocation
    anchor: anchors.TrustAnchor


class Prepare(Protocol):
    def __call__(
        self, ports: portset.HostPorts, *, original: Trial, scratch: verifying.BundleLocation
    ) -> Trial: ...


@dataclasses.dataclass(frozen=True, slots=True)
class Negative:
    id: identifiers.FaultId
    expects: refusals.RefusalReason
    prepare: Prepare


_collector: registry.Registry[str, Negative] = registry.Registry("negative")
_sealed: registry.SealedRegistry[str, Negative] | None = None


def declare(negative: Negative) -> Negative:
    _collector.add(str(negative.id), negative, at=decorators.caller(2))
    return negative


def sealed() -> registry.SealedRegistry[str, Negative]:
    global _sealed
    if _sealed is None:
        discovery.discover([__name__])
        _sealed = _collector.seal()
    return _sealed


def registered() -> tuple[Negative, ...]:
    return tuple(negative for _, negative in sorted(sealed().items(), key=lambda item: item[0]))

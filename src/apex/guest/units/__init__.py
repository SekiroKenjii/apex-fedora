"""What a guest can be asked to do, one module each.

This module never names a unit. Dropping a file into this directory registers one, and a
request for a unit no file declares is refused by name.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from apex.guest import agentports
from apex.kernel import encoding, errors, identifiers, refusals
from apex.registry import decorators, discovery, registry

DIRECTORY = Path(__file__).resolve().parent


class Run(Protocol):
    def __call__(
        self, ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
    ) -> encoding.Document: ...


@dataclasses.dataclass(frozen=True, slots=True)
class Unit:
    id: identifiers.ProbeId
    run: Run


_collector: registry.Registry[str, Unit] = registry.Registry("unit")
_sealed: registry.SealedRegistry[str, Unit] | None = None


def declare(unit: Unit) -> Unit:
    _collector.add(str(unit.id), unit, at=decorators.caller(2))
    return unit


def sealed() -> registry.SealedRegistry[str, Unit]:
    global _sealed
    if _sealed is None:
        discovery.discover([__name__])
        _sealed = _collector.seal()
    return _sealed


def registered() -> tuple[Unit, ...]:
    return tuple(unit for _, unit in sorted(sealed().items(), key=lambda item: item[0]))


def lookup(name: identifiers.ProbeId) -> Unit:
    if str(name) not in sealed():
        raise errors.Refusal(
            refusals.RefusalReason.UNIT_UNKNOWN,
            subject=str(name),
            remedy=f"this guest answers for: {', '.join(sorted(sealed()))}",
        )
    return sealed().lookup(str(name))

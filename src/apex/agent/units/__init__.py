"""What a guest can be asked to do, one module each.

This module never names a unit. Dropping a file into this directory registers one, and a
request for a unit no file declares is refused by name.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from apex.agent import agentports
from apex.kernel import encoding, identifiers
from apex.registry import casebook, registry

DIRECTORY = Path(__file__).resolve().parent


class Run(Protocol):
    def __call__(
        self, ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
    ) -> encoding.Document: ...


@dataclasses.dataclass(frozen=True, slots=True)
class Unit:
    id: identifiers.ProbeId
    run: Run


BOOK: casebook.Casebook[Unit] = casebook.Casebook(
    kind="unit", namespace=__name__, key=lambda unit: str(unit.id), known="this guest answers for"
)


def declare(unit: Unit) -> Unit:
    return BOOK.declare(unit)


def sealed() -> registry.SealedRegistry[str, Unit]:
    return BOOK.sealed()


def registered() -> tuple[Unit, ...]:
    return BOOK.registered()


def lookup(name: identifiers.ProbeId) -> Unit:
    return BOOK.lookup(name)

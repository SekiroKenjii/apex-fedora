"""The fault cases, one module each; adding a fault is adding a file here and a unit in the agent.

This module never names a case. A case for a unit the agent does not declare is a fault the
tests find, because the agent's units and the cases here are compared by name.
"""

from __future__ import annotations

from pathlib import Path

from apex.kernel import identifiers
from apex.registry import casebook, registry
from apex.verification import faulting

DIRECTORY = Path(__file__).resolve().parent
BOOK: casebook.Casebook[faulting.FaultCase] = casebook.Casebook(
    kind="fault",
    namespace=__name__,
    key=lambda case: str(case.unit),
    known="the host knows these faults",
)


def declare(case: faulting.FaultCase) -> faulting.FaultCase:
    return BOOK.declare(case)


def sealed() -> registry.SealedRegistry[str, faulting.FaultCase]:
    return BOOK.sealed()


def registered() -> tuple[faulting.FaultCase, ...]:
    return BOOK.registered()


def lookup(name: identifiers.ProbeId) -> faulting.FaultCase:
    return BOOK.lookup(name)

"""The probe cases, one module each; adding a probe is adding a file here and one in the agent.

This module never names a case. A case for a unit the agent does not declare is a fault the
tests find, because the agent's units and the cases here are compared by name.
"""

from __future__ import annotations

from pathlib import Path

from apex.kernel import identifiers
from apex.registry import casebook, registry
from apex.verification import probing

DIRECTORY = Path(__file__).resolve().parent
BOOK: casebook.Casebook[probing.ProbeCase] = casebook.Casebook(
    kind="probe",
    namespace=__name__,
    key=lambda case: str(case.unit),
    known="the host knows these probes",
)


def declare(case: probing.ProbeCase) -> probing.ProbeCase:
    return BOOK.declare(case)


def sealed() -> registry.SealedRegistry[str, probing.ProbeCase]:
    return BOOK.sealed()


def registered() -> tuple[probing.ProbeCase, ...]:
    return BOOK.registered()


def lookup(name: identifiers.ProbeId) -> probing.ProbeCase:
    return BOOK.lookup(name)

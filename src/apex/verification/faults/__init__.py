"""The fault cases, one module each; adding a fault is adding a file here and a unit in the agent.

This module never names a case. A case for a unit the agent does not declare is a fault the
tests find, because the agent's units and the cases here are compared by name.
"""

from __future__ import annotations

from pathlib import Path

from apex.kernel import errors, identifiers, refusals
from apex.registry import decorators, discovery, registry
from apex.verification import faulting

DIRECTORY = Path(__file__).resolve().parent

_collector: registry.Registry[str, faulting.FaultCase] = registry.Registry("fault")
_sealed: registry.SealedRegistry[str, faulting.FaultCase] | None = None


def declare(case: faulting.FaultCase) -> faulting.FaultCase:
    _collector.add(str(case.unit), case, at=decorators.caller(2))
    return case


def sealed() -> registry.SealedRegistry[str, faulting.FaultCase]:
    global _sealed
    if _sealed is None:
        discovery.discover([__name__])
        _sealed = _collector.seal()
    return _sealed


def registered() -> tuple[faulting.FaultCase, ...]:
    return tuple(case for _, case in sorted(sealed().items(), key=lambda item: item[0]))


def lookup(name: identifiers.ProbeId) -> faulting.FaultCase:
    if str(name) not in sealed():
        raise errors.Refusal(
            refusals.RefusalReason.UNIT_UNKNOWN,
            subject=str(name),
            remedy=f"the host knows these faults: {', '.join(sorted(sealed()))}",
        )
    return sealed().lookup(str(name))

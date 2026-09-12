"""The probe cases, one module each; adding a probe is adding a file here and one in the agent.

This module never names a case. A case for a unit the agent does not declare is a fault the
tests find, because the agent's units and the cases here are compared by name.
"""

from __future__ import annotations

from pathlib import Path

from apex.kernel import errors, identifiers, refusals
from apex.registry import decorators, discovery, registry
from apex.verification import probing

DIRECTORY = Path(__file__).resolve().parent

_collector: registry.Registry[str, probing.ProbeCase] = registry.Registry("probe")
_sealed: registry.SealedRegistry[str, probing.ProbeCase] | None = None


def declare(case: probing.ProbeCase) -> probing.ProbeCase:
    _collector.add(str(case.unit), case, at=decorators.caller(2))
    return case


def sealed() -> registry.SealedRegistry[str, probing.ProbeCase]:
    global _sealed
    if _sealed is None:
        discovery.discover([__name__])
        _sealed = _collector.seal()
    return _sealed


def registered() -> tuple[probing.ProbeCase, ...]:
    return tuple(case for _, case in sorted(sealed().items(), key=lambda item: item[0]))


def lookup(name: identifiers.ProbeId) -> probing.ProbeCase:
    if str(name) not in sealed():
        raise errors.Refusal(
            refusals.RefusalReason.UNIT_UNKNOWN,
            subject=str(name),
            remedy=f"the host knows these probes: {', '.join(sorted(sealed()))}",
        )
    return sealed().lookup(str(name))

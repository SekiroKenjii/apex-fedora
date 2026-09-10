"""The required checks, one module each.

A check that is not registered does not exist, so the readiness fold cannot report ready by
forgetting one. Registering a new check makes it blocking the instant it lands.
"""

from __future__ import annotations

from apex.kernel import identifiers
from apex.registry import decorators, descriptors, discovery, registry

NAMESPACES = ("build", "git", "hardware", "recovery", "vm")

_collector = decorators.Collector()
_sealed: registry.SealedRegistry[str, descriptors.CheckSpec] | None = None


def declare(spec: descriptors.CheckSpec) -> descriptors.CheckSpec:
    return _collector.check(spec, depth=3)


def sealed() -> registry.SealedRegistry[str, descriptors.CheckSpec]:
    """Import every check module once, then seal. Repeated calls return the same registry."""
    global _sealed
    if _sealed is None:
        discovery.discover([f"{__name__}.{name}" for name in NAMESPACES])
        _sealed = _collector.checks.seal()
    return _sealed


def specification(check: identifiers.CheckId) -> descriptors.CheckSpec:
    return sealed().lookup(str(check))

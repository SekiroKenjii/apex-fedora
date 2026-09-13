"""The readers, one module each, keyed by the mark they claim.

This module never names a reader. Dropping a file into this directory is the whole act of
registering one, and removing every mention of a version from anywhere else is what makes
supporting a later store a new file rather than an edit.
"""

from __future__ import annotations

from apex.attestation import readerspecs
from apex.registry import decorators, discovery, registry

_collector: registry.Registry[str, readerspecs.StoreReaderSpec] = registry.Registry("store reader")
_sealed: registry.SealedRegistry[str, readerspecs.StoreReaderSpec] | None = None


def declare(spec: readerspecs.StoreReaderSpec) -> readerspecs.StoreReaderSpec:
    at = decorators.caller(2)
    for claim in spec.marks:
        _collector.add(claim.key(), spec, at=at)
    return spec


def sealed() -> registry.SealedRegistry[str, readerspecs.StoreReaderSpec]:
    global _sealed
    if _sealed is None:
        discovery.discover([__name__])
        _sealed = _collector.seal()
    return _sealed

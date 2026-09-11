"""The hooks the repository rules answer, one module each.

This module never names a kind. Dropping a file into this directory is the whole act of
transferring one hook, and deleting that file is the whole act of giving it back.
"""

from __future__ import annotations

from apex.cli import hookspecs
from apex.registry import decorators, discovery, registry

_collector: registry.Registry[str, hookspecs.HookKind] = registry.Registry("hook kind")
_sealed: registry.SealedRegistry[str, hookspecs.HookKind] | None = None


def declare(kind: hookspecs.HookKind) -> hookspecs.HookKind:
    _collector.add(kind.name, kind, at=decorators.caller(2))
    return kind


def sealed() -> registry.SealedRegistry[str, hookspecs.HookKind]:
    global _sealed
    if _sealed is None:
        discovery.discover([__name__])
        _sealed = _collector.seal()
    return _sealed


def names() -> tuple[str, ...]:
    return tuple(sorted(sealed()))


def lookup(name: str) -> hookspecs.HookKind | None:
    registered = sealed()
    return registered.lookup(name) if name in registered else None

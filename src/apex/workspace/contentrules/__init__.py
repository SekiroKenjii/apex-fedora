"""Rules about what a tracked file contains.

This module never names a rule. Dropping a file into this directory is the whole act of
registering one, and two units claiming a single identifier fail the seal.
"""

from __future__ import annotations

from apex.registry import decorators, discovery, registry
from apex.workspace import rulespecs

_collector: registry.Registry[str, rulespecs.ContentRule] = registry.Registry("content rule")
_sealed: registry.SealedRegistry[str, rulespecs.ContentRule] | None = None


def declare(rule: rulespecs.ContentRule) -> rulespecs.ContentRule:
    _collector.add(str(rule.id), rule, at=decorators.caller(2))
    return rule


def sealed() -> registry.SealedRegistry[str, rulespecs.ContentRule]:
    global _sealed
    if _sealed is None:
        discovery.discover([__name__])
        _sealed = _collector.seal()
    return _sealed


def registered() -> tuple[rulespecs.ContentRule, ...]:
    """Every rule, ordered by identifier so a run does not depend on import order."""
    return tuple(rule for _, rule in sorted(sealed().items(), key=lambda item: item[0]))

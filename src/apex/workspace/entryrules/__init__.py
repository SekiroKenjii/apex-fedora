"""Rules about where a tracked file sits and what kind of thing it is.

This module never names a rule. Dropping a file into this directory is the whole act of
registering one, and two units claiming a single identifier fail the seal.
"""

from __future__ import annotations

from apex.registry import decorators, discovery, registry
from apex.workspace import rulespecs

_collector: registry.Registry[str, rulespecs.EntryRule] = registry.Registry("entry rule")
_sealed: registry.SealedRegistry[str, rulespecs.EntryRule] | None = None


def declare(rule: rulespecs.EntryRule) -> rulespecs.EntryRule:
    _collector.add(str(rule.id), rule, at=decorators.caller(2))
    return rule


def sealed() -> registry.SealedRegistry[str, rulespecs.EntryRule]:
    global _sealed
    if _sealed is None:
        discovery.discover([__name__])
        _sealed = _collector.seal()
    return _sealed


def registered() -> tuple[rulespecs.EntryRule, ...]:
    """Every rule, ordered by identifier so a run does not depend on import order."""
    return tuple(rule for _, rule in sorted(sealed().items(), key=lambda item: item[0]))

"""Rules about the subject line a commit carries.

This module never names a rule. Dropping a file into this directory is the whole act of
registering one, and two units claiming a single identifier fail the seal.
"""

from __future__ import annotations

from apex.registry import decorators, discovery, registry
from apex.workspace import rulespecs

TRAILING_NEWLINE = "\n"

_collector: registry.Registry[str, rulespecs.MessageRule] = registry.Registry("message rule")
_sealed: registry.SealedRegistry[str, rulespecs.MessageRule] | None = None


def declare(rule: rulespecs.MessageRule) -> rulespecs.MessageRule:
    _collector.add(str(rule.id), rule, at=decorators.caller(2))
    return rule


def sealed() -> registry.SealedRegistry[str, rulespecs.MessageRule]:
    global _sealed
    if _sealed is None:
        discovery.discover([__name__])
        _sealed = _collector.seal()
    return _sealed


def registered() -> tuple[rulespecs.MessageRule, ...]:
    """Every rule, ordered by identifier so a run does not depend on import order."""
    return tuple(rule for _, rule in sorted(sealed().items(), key=lambda item: item[0]))


def subject_line(subject: rulespecs.MessageSubject) -> str:
    """The message with the newline Git appends removed, which is what the rules read."""
    return subject.raw.removesuffix(TRAILING_NEWLINE)

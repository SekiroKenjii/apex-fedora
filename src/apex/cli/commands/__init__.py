"""The commands the tree answers for, one module each.

This module never names a command. Dropping a file into this directory is the whole act of
adding one, and a name no file declares falls through to the bridge into the older tree for
as long as that tree exists.
"""

from __future__ import annotations

from apex.cli import commandspecs
from apex.registry import decorators, discovery, registry

_collector: registry.Registry[str, commandspecs.Command] = registry.Registry("command")
_sealed: registry.SealedRegistry[str, commandspecs.Command] | None = None


def declare(command: commandspecs.Command) -> commandspecs.Command:
    _collector.add(command.name, command, at=decorators.caller(2))
    return command


def sealed() -> registry.SealedRegistry[str, commandspecs.Command]:
    global _sealed
    if _sealed is None:
        discovery.discover([__name__])
        _sealed = _collector.seal()
    return _sealed


def names() -> tuple[str, ...]:
    return tuple(sorted(sealed()))


def lookup(name: str) -> commandspecs.Command | None:
    registered = sealed()
    return registered.lookup(name) if name in registered else None

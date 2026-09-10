"""Derive execution order from what each unit reads and writes.

The real constraint is data availability, not somebody's idea of sequence. Deriving it means
inserting a step never requires editing the steps around it, and it means a cycle or a
missing producer is a load-time error rather than a surprise part way through a run.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from apex.kernel import errors


@dataclasses.dataclass(frozen=True, slots=True)
class Node:
    id: str
    reads: frozenset[str]
    writes: frozenset[str]


def order(nodes: Sequence[Node], *, seeds: frozenset[str] = frozenset()) -> list[str]:
    producers: dict[str, str] = {}
    for node in sorted(nodes, key=lambda item: item.id):
        for fact in sorted(node.writes):
            claimed = producers.get(fact)
            if claimed is not None:
                raise errors.RegistrationError(
                    f"{fact!r} is written by both {claimed!r} and {node.id!r}"
                )
            producers[fact] = node.id

    dependencies: dict[str, set[str]] = {node.id: set() for node in nodes}
    for node in nodes:
        for fact in sorted(node.reads):
            if fact in seeds:
                continue
            producer = producers.get(fact)
            if producer is None:
                raise errors.RegistrationError(
                    f"{node.id!r} reads {fact!r}, which no registered unit writes"
                )
            if producer != node.id:
                dependencies[node.id].add(producer)

    remaining = dict(dependencies)
    resolved: list[str] = []
    while remaining:
        ready = sorted(name for name, needs in remaining.items() if not needs)
        if not ready:
            stuck = ", ".join(sorted(remaining))
            raise errors.RegistrationError(f"these units depend on each other: {stuck}")
        for name in ready:
            resolved.append(name)
            del remaining[name]
        for needs in remaining.values():
            needs.difference_update(ready)
    return resolved

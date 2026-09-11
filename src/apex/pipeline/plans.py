"""A plan is a named stage set. The order is derived, and the digest identifies it."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

from apex.kernel import encoding, hashing, identifiers
from apex.pipeline.facts import FactKey
from apex.pipeline.stages import Stage
from apex.registry import graph


@dataclasses.dataclass(frozen=True, slots=True)
class Plan[P]:
    name: str
    stages: tuple[Stage[P], ...]
    order: tuple[identifiers.StageId, ...]
    digest: identifiers.Digest

    @classmethod
    def of(
        cls,
        name: str,
        declared: Sequence[Stage[P]],
        *,
        seeds: frozenset[FactKey[Any]] = frozenset(),
    ) -> Plan[P]:
        nodes = [
            graph.Node(
                id=str(item.id),
                reads=frozenset(key.name for key in item.reads),
                writes=frozenset(key.name for key in item.writes),
            )
            for item in declared
        ]
        ordered = graph.order(nodes, seeds=frozenset(key.name for key in seeds))
        by_name = {str(item.id): item for item in declared}
        sequence = tuple(identifiers.StageId(item) for item in ordered)
        return cls(
            name=name,
            stages=tuple(by_name[item] for item in ordered),
            order=sequence,
            digest=_digest(name, [by_name[item] for item in ordered]),
        )


def render(plan: Plan[Any]) -> encoding.Document:
    """The plan as an operator reads it and as the golden copy records it."""
    return {
        "name": plan.name,
        "digest": plan.digest.hex,
        "stages": _describe(plan.stages),
    }


def _digest(name: str, ordered: Sequence[Stage[Any]]) -> identifiers.Digest:
    document: encoding.Document = {"name": name, "stages": _describe(ordered)}
    return hashing.digest_bytes(encoding.canonical(document))


def _describe(ordered: Sequence[Stage[Any]]) -> list[encoding.JsonValue]:
    return [
        {
            "id": str(item.id),
            "reads": sorted(key.name for key in item.reads),
            "writes": sorted(key.name for key in item.writes),
            "effects": sorted(str(effect) for effect in item.effects),
            "attests": sorted(str(check) for check in item.attests),
        }
        for item in ordered
    ]

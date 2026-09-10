"""A plan is a named stage set. The order is derived, and the digest identifies it."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from typing import Any, Self

from apex.kernel import hashing, identifiers
from apex.pipeline.facts import FactKey
from apex.pipeline.stages import Stage
from apex.registry import graph


@dataclasses.dataclass(frozen=True, slots=True)
class Plan:
    name: str
    stages: tuple[Stage, ...]
    order: tuple[identifiers.StageId, ...]
    digest: identifiers.Digest

    @classmethod
    def of(
        cls,
        name: str,
        declared: Sequence[Stage],
        *,
        seeds: frozenset[FactKey[Any]] = frozenset(),
    ) -> Self:
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


def _digest(name: str, ordered: Sequence[Stage]) -> identifiers.Digest:
    canonical = json.dumps(
        {
            "name": name,
            "stages": [
                {
                    "id": str(item.id),
                    "reads": sorted(key.name for key in item.reads),
                    "writes": sorted(key.name for key in item.writes),
                    "effects": sorted(str(effect) for effect in item.effects),
                    "attests": sorted(str(check) for check in item.attests),
                }
                for item in ordered
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashing.digest_bytes(canonical.encode())

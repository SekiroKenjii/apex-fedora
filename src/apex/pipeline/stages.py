"""The stage contract.

`apply` never raises to control the flow. It returns a closed union, so a caller that forgets
a case is a type error rather than an unhandled path. The bundle of ports a stage sees is a
type parameter, so a stage written for the host bundle cannot be run with the agent's.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from apex.kernel import identifiers, refusals
from apex.pipeline import effects
from apex.pipeline.facts import FactKey, FactMap


@dataclasses.dataclass(frozen=True, slots=True)
class Ready:
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class SkipBecause:
    reason: refusals.RefusalReason
    detail: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class RefuseBecause:
    reason: refusals.RefusalReason
    detail: str = ""


type Preflight = Ready | SkipBecause | RefuseBecause


@dataclasses.dataclass(frozen=True, slots=True)
class Finaliser:
    name: str
    release: Callable[[], None]


@dataclasses.dataclass(frozen=True, slots=True)
class Advance:
    facts: Mapping[FactKey[Any], Any] = dataclasses.field(default_factory=dict)
    finaliser: Finaliser | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class Skip:
    reason: refusals.RefusalReason
    detail: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class Refuse:
    reason: refusals.RefusalReason
    detail: str = ""


@dataclasses.dataclass(frozen=True, slots=True)
class Fail:
    cause: str


type StageResult = Advance | Skip | Refuse | Fail


@dataclasses.dataclass(frozen=True, slots=True)
class RunContext[P]:
    facts: FactMap
    ports: P

    def with_facts(
        self, produced: Mapping[FactKey[Any], Any], *, by: identifiers.StageId
    ) -> RunContext[P]:
        updated = self.facts
        for key, value in produced.items():
            updated = updated.with_fact(key, value, produced_by=by)
        return RunContext(facts=updated, ports=self.ports)


class Stage[P](Protocol):
    id: identifiers.StageId
    reads: tuple[FactKey[Any], ...]
    writes: tuple[FactKey[Any], ...]
    attests: frozenset[identifiers.CheckId]
    effects: frozenset[effects.Effect]

    def preflight(self, context: RunContext[P]) -> Preflight: ...

    def apply(self, context: RunContext[P]) -> StageResult: ...


@dataclasses.dataclass(frozen=True, slots=True)
class SimpleStage[P]:
    """A stage assembled from two callables. Used by tests and by small units."""

    id: identifiers.StageId
    reads: tuple[FactKey[Any], ...]
    writes: tuple[FactKey[Any], ...]
    attests: frozenset[identifiers.CheckId]
    effects: frozenset[effects.Effect]
    preflight: Callable[[RunContext[P]], Preflight]
    apply: Callable[[RunContext[P]], StageResult]

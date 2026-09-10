"""What a stage learned, keyed so the reader knows the type.

A fact is written once. A second write is a defect rather than a silent overwrite, because
two stages claiming the same fact means the plan is wrong, not that the later one wins.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from apex.kernel import errors, identifiers


@dataclasses.dataclass(frozen=True, slots=True)
class FactKey[T]:
    name: str

    def __str__(self) -> str:
        return self.name


@dataclasses.dataclass(frozen=True, slots=True)
class Fact:
    value: Any
    produced_by: identifiers.StageId


class FactMap:
    __slots__ = ("_entries",)

    def __init__(self, entries: dict[str, Fact] | None = None) -> None:
        self._entries = dict(entries or {})

    def __contains__(self, key: FactKey[Any]) -> bool:
        return key.name in self._entries

    def __getitem__[T](self, key: FactKey[T]) -> T:
        try:
            return self._entries[key.name].value  # type: ignore[no-any-return]
        except KeyError as error:
            known = ", ".join(sorted(self._entries)) or "nothing"
            raise errors.InternalDefect(
                f"{key.name!r} was read before any stage wrote it; the map holds {known}"
            ) from error

    def producer(self, key: FactKey[Any]) -> identifiers.StageId:
        return self._entries[key.name].produced_by

    def with_fact[T](
        self, key: FactKey[T], value: T, *, produced_by: identifiers.StageId
    ) -> FactMap:
        if key.name in self._entries:
            already = self._entries[key.name].produced_by
            raise errors.InternalDefect(
                f"{key.name!r} was written by {already} and again by {produced_by}"
            )
        return FactMap({**self._entries, key.name: Fact(value, produced_by)})

    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._entries))

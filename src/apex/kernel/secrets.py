"""Material that must never be rendered.

Every route a value normally takes into a log or a report is closed, so reaching a sink is
the only way to use one.
"""

from __future__ import annotations

import dataclasses
import enum
from typing import Protocol

from apex.kernel import errors, refusals


class SecretSink(Protocol):
    def accept(self, material: str) -> None: ...


class Lifetime(enum.StrEnum):
    DISPOSABLE_FIXTURE = "disposable-fixture"
    BUILDER_RESIDENT = "builder-resident"
    OPERATOR_SUPPLIED = "operator-supplied"


class Secret[T]:
    __slots__ = ("_material",)

    def __init__(self, material: T) -> None:
        self._material = material

    def reveal_into(self, sink: SecretSink) -> None:
        sink.accept(self._material)  # type: ignore[arg-type]

    def __repr__(self) -> str:
        return "<redacted>"

    def __str__(self) -> str:
        raise errors.Refusal(
            refusals.RefusalReason.SECRET_NOT_RENDERABLE,
            subject="Secret",
            remedy="expose it into a declared sink instead",
        )

    def __format__(self, specification: str) -> str:
        return self.__str__()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Secret):
            return NotImplemented
        return bool(self._material == other._material)

    def __hash__(self) -> int:
        return hash(("Secret", self._material))


class CollectingSink:
    """A sink that keeps what it was given. Used by tests and by the file vault."""

    def __init__(self) -> None:
        self.collected: str | None = None

    def accept(self, material: str) -> None:
        self.collected = material


@dataclasses.dataclass(frozen=True, slots=True)
class CredentialHandle:
    purpose: str
    lifetime: Lifetime

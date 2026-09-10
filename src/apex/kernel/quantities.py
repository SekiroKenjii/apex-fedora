"""Scalars that carry their unit, so a mebibyte cannot be added to a gibibyte."""

from __future__ import annotations

import dataclasses
from typing import Self

from apex.kernel import errors, refusals

BYTES_PER_MEBIBYTE = 1024**2
BYTES_PER_GIBIBYTE = 1024**3
HIGHEST_TCP_PORT = 65535
# The project never sets a setuid, setgid or sticky bit; refusing them here makes an
# accidental one impossible to express.
PERMISSION_BITS = 0o777


@dataclasses.dataclass(frozen=True, slots=True, order=True)
class ByteCount:
    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise errors.Refusal(
                refusals.RefusalReason.NEGATIVE_QUANTITY, subject=f"{self.value} bytes"
            )

    def __add__(self, other: Self) -> Self:
        if type(other) is not type(self):
            return NotImplemented
        return type(self)(self.value + other.value)


@dataclasses.dataclass(frozen=True, slots=True, order=True)
class Mib(ByteCount):
    @property
    def bytes(self) -> int:
        return self.value * BYTES_PER_MEBIBYTE

    def as_bytes(self) -> ByteCount:
        return ByteCount(self.bytes)


@dataclasses.dataclass(frozen=True, slots=True, order=True)
class Gib(ByteCount):
    @property
    def bytes(self) -> int:
        return self.value * BYTES_PER_GIBIBYTE

    def as_bytes(self) -> ByteCount:
        return ByteCount(self.bytes)


@dataclasses.dataclass(frozen=True, slots=True, order=True)
class TcpPort:
    value: int

    def __post_init__(self) -> None:
        if not 1 <= self.value <= HIGHEST_TCP_PORT:
            raise errors.Refusal(
                refusals.RefusalReason.PORT_OUT_OF_RANGE, subject=str(self.value)
            )

    def __str__(self) -> str:
        return str(self.value)


@dataclasses.dataclass(frozen=True, slots=True)
class FileMode:
    value: int

    def __post_init__(self) -> None:
        if not 0 <= self.value <= PERMISSION_BITS:
            raise errors.Refusal(
                refusals.RefusalReason.MODE_OUT_OF_RANGE, subject=oct(self.value)
            )

    def __str__(self) -> str:
        return f"{self.value:04o}"

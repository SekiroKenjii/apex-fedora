"""Reading untrusted output without letting it decide how much memory to use."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

from apex.kernel import errors, refusals


@dataclasses.dataclass(frozen=True, slots=True)
class Limit:
    value: int

    def __post_init__(self) -> None:
        if self.value <= 0:
            raise errors.Refusal(refusals.RefusalReason.LIMIT_NOT_POSITIVE, subject=str(self.value))


CAPTURE_LIMIT = Limit(262144)
SERIAL_CHUNK = Limit(768)


@dataclasses.dataclass(frozen=True, slots=True)
class Bounded:
    data: bytes
    truncated: bool


def take(data: bytes, limit: Limit) -> Bounded:
    return Bounded(data[: limit.value], len(data) > limit.value)


class BoundedRingBuffer:
    """Retain the tail of a stream and report how much was discarded."""

    def __init__(self, limit: Limit) -> None:
        self._limit = limit
        self._data = bytearray()
        self.dropped = 0

    def append(self, chunk: bytes) -> None:
        self._data.extend(chunk)
        excess = len(self._data) - self._limit.value
        if excess > 0:
            del self._data[:excess]
            self.dropped += excess

    def tail(self) -> bytes:
        return bytes(self._data)


def bounded_lines(data: bytes, line_limit: Limit, *, maximum_lines: int) -> Iterator[bytes]:
    for index, line in enumerate(data.splitlines()):
        if index >= maximum_lines:
            return
        if len(line) > line_limit.value:
            raise errors.Refusal(
                refusals.RefusalReason.LINE_EXCEEDS_LIMIT, subject=f"line {index + 1}"
            )
        yield line

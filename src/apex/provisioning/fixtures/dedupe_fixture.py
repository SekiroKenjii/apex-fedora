"""Sharing identical blob extents between two fixture bundles without removing a file.

The ioctl layout and the range rules are decided here; the call itself, on the builder's
Btrfs scratch, is the agent's.
"""

from __future__ import annotations

import dataclasses
import struct

from apex.kernel import errors, quantities, refusals

# Linux x86_64 UAPI: _IOWR(0x94, 54, struct file_dedupe_range).
FIDEDUPERANGE = 0xC0189436
HEADER = struct.Struct("=QQHHI")
INFO = struct.Struct("=qQQiI")
CHUNK = quantities.Mib(16)
ALIGNMENT = 4096
SAME_DATA = 0


@dataclasses.dataclass(frozen=True, slots=True)
class DedupeRange:
    offset: int
    length: int

    def __post_init__(self) -> None:
        aligned = self.offset % ALIGNMENT == 0 and self.length % ALIGNMENT == 0
        if self.offset < 0 or self.length <= 0 or not aligned:
            raise errors.Refusal(
                refusals.RefusalReason.FIXTURE_REQUEST_MALFORMED,
                subject="dedupe ranges must use positive aligned lengths",
            )


@dataclasses.dataclass(frozen=True, slots=True)
class DedupeOutcome:
    bytes_deduped: int
    status: int

    @property
    def complete(self) -> bool:
        return self.status == SAME_DATA


def request_buffer(span: DedupeRange, target_descriptor: int) -> bytearray:
    return bytearray(
        HEADER.pack(span.offset, span.length, 1, 0, 0)
        + INFO.pack(target_descriptor, span.offset, 0, 0, 0)
    )


def outcome_of(buffer: bytearray) -> DedupeOutcome:
    _, _, count, status, _ = INFO.unpack_from(buffer, HEADER.size)
    return DedupeOutcome(bytes_deduped=count, status=status)


def shareable_length(size: int) -> int:
    """The aligned prefix of a blob; the tail below one block is never submitted."""
    return size // ALIGNMENT * ALIGNMENT


def spans(size: int) -> tuple[DedupeRange, ...]:
    total = shareable_length(size)
    return tuple(
        DedupeRange(offset, min(CHUNK.bytes, total - offset))
        for offset in range(0, total, CHUNK.bytes)
    )

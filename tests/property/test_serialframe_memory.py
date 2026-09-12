"""The frame decoder holds a bounded amount of memory whatever a guest writes.

The threshold in the specification is one gibibyte of hostile bytes under four mebibytes of
memory. Feeding a gibibyte through the fast suite is not affordable, so each shape is fed
at sixty four mebibytes; memory that is constant over that range does not grow after it.
"""

from __future__ import annotations

import tracemalloc
from collections.abc import Iterator

import pytest

from apex.agent import serialframe
from apex.kernel import identifiers

TOKEN = identifiers.Token("a" * 32)
PIECE = 64 * 1024
TOTAL = 64 * 1024 * 1024
MEMORY_BOUND = 4 * 1024 * 1024


def no_newline_ever() -> Iterator[bytes]:
    for _ in range(TOTAL // PIECE):
        yield b"x" * PIECE


def lines_that_are_not_frames() -> Iterator[bytes]:
    line = b"kernel: something happened that is not a frame line\n"
    piece = line * (PIECE // len(line))
    for _ in range(TOTAL // PIECE):
        yield piece


def chunk_lines_with_the_wrong_token() -> Iterator[bytes]:
    line = b"APEXLOG:" + b"b" * 32 + b":0:" + b"A" * 700 + b"\n"
    piece = line * (PIECE // len(line))
    for _ in range(TOTAL // PIECE):
        yield piece


@pytest.mark.parametrize(
    "stream", [no_newline_ever, lines_that_are_not_frames, chunk_lines_with_the_wrong_token]
)
def test_hostile_bytes_do_not_grow_the_decoder(stream: object) -> None:
    decoder = serialframe.FrameDecoder(token=TOKEN)
    tracemalloc.start()
    try:
        baseline, _ = tracemalloc.get_traced_memory()
        for piece in stream():  # type: ignore[operator]
            assert decoder.feed(piece) is None
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert peak - baseline < MEMORY_BOUND
    assert decoder.pending_bytes <= serialframe.LINE_LIMIT.value

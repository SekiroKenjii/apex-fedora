"""A screenshot as the hypervisor dumps it, and the two judgements the older tool made over it.

A frame is a binary PPM: three header lines, then three bytes per pixel. The judgements scan
rows as buffers rather than pixels in a loop: a row equal to its counterpart is skipped
whole, and a colour class is found by translating each channel through a table and joining
the channels as wide integers, so a 1280 by 800 frame costs a few buffer operations per row.
Each judgement is a value the host records; a frame that cannot be read or compared is
refused, because that is a broken capture and not a failed check.
"""

from __future__ import annotations

import dataclasses
import functools
import operator
import re
from collections.abc import Callable
from typing import Self

from apex.kernel import encoding, errors, refusals

MAGIC = b"P6"
MAXIMUM = b"255"
CHANNELS = 3
NOT_TESTED = "NOT TESTED"

ROW_STRIDE = 4
BAR_RUN = 80
BAR_GAP = 4
BAR_ROWS = 20
RED_LEAST = 180
OTHERS_UNDER_RED = 90
GREEN_LEAST = 140
RED_UNDER_GREEN = 100
BLUE_UNDER_GREEN = 120
BLUE_LEAST = 180
RED_UNDER_BLUE = 100
GREEN_UNDER_BLUE = 120

TOP_BAR_ROWS = 40
CHANGE = 20
MINIMUM_CHANGED = 5000
CHANGED_SHARE = 100

NONE, RED, GREEN, BLUE = 0, 1, 2, 3


def _table(test: Callable[[int], bool]) -> bytes:
    return bytes(1 if test(value) else 0 for value in range(256))


RED_HIGH = _table(lambda value: value > RED_LEAST)
UNDER_RED = _table(lambda value: value < OTHERS_UNDER_RED)
GREEN_HIGH = _table(lambda value: value > GREEN_LEAST)
RED_LOW_FOR_GREEN = _table(lambda value: value < RED_UNDER_GREEN)
BLUE_LOW_FOR_GREEN = _table(lambda value: value < BLUE_UNDER_GREEN)
BLUE_HIGH = _table(lambda value: value > BLUE_LEAST)
RED_LOW_FOR_BLUE = _table(lambda value: value < RED_UNDER_BLUE)
GREEN_LOW_FOR_BLUE = _table(lambda value: value < GREEN_UNDER_BLUE)


def _bars_pattern() -> re.Pattern[bytes]:
    run = b"{%d,}" % BAR_RUN
    gap = bytes([NONE]) + b"{0,%d}" % BAR_GAP
    return re.compile(
        bytes([RED]) + run + gap + bytes([GREEN]) + run + gap + bytes([BLUE]) + run
    )


BARS = _bars_pattern()
DIFFERING = re.compile(rb"[^\x00]+")


def _refuse(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.MALFORMED_SCREEN_FRAME, subject=detail)


@dataclasses.dataclass(frozen=True, slots=True)
class Frame:
    width: int
    height: int
    pixels: bytes

    @classmethod
    def parse(cls, payload: bytes) -> Self:
        parts = payload.split(b"\n", 3)
        if len(parts) != 4 or parts[0].strip() != MAGIC or parts[2].strip() != MAXIMUM:
            raise _refuse("not a binary PPM with one byte per channel")
        dimensions = parts[1].split()
        if len(dimensions) != 2 or not all(item.isdigit() for item in dimensions):
            raise _refuse("the dimensions are not two integers")
        width, height = (int(item) for item in dimensions)
        if width <= 0 or height <= 0:
            raise _refuse("an empty frame")
        if len(parts[3]) != width * height * CHANNELS:
            raise _refuse(f"{len(parts[3])} bytes for {width} by {height}")
        return cls(width=width, height=height, pixels=parts[3])

    @property
    def stride(self) -> int:
        return self.width * CHANNELS

    def row(self, index: int) -> memoryview:
        return memoryview(self.pixels)[index * self.stride : (index + 1) * self.stride]


@dataclasses.dataclass(frozen=True, slots=True)
class Bars:
    """How many sampled rows carry the three adjacent wide bars the render probe draws."""

    width: int
    height: int
    matched_rows: int

    @property
    def visible(self) -> bool:
        return self.matched_rows >= BAR_ROWS

    def document(self) -> encoding.Document:
        return {
            "width": self.width,
            "height": self.height,
            "matched_rows_at_stride_four": self.matched_rows,
            "minimum_rows": BAR_ROWS,
            "visible": self.visible,
        }


@dataclasses.dataclass(frozen=True, slots=True)
class SurfaceChange:
    """How many pixels below the top bar changed between two captures of the Shell."""

    changed_pixels: int
    minimum_pixels: int

    @property
    def visible(self) -> bool:
        return self.changed_pixels >= self.minimum_pixels

    def document(self) -> encoding.Document:
        return {
            "changed_pixels": self.changed_pixels,
            "minimum_pixels": self.minimum_pixels,
            "visible": self.visible,
            "visual_identification": NOT_TESTED,
        }


def _wide(*masks: bytes) -> int:
    return functools.reduce(operator.and_, (int.from_bytes(mask, "big") for mask in masks))


def _classes(row: memoryview, width: int) -> bytes:
    """One byte per pixel naming its colour class, computed channel-wise over the whole row."""
    red, green, blue = (row[channel::CHANNELS].tobytes() for channel in range(CHANNELS))
    reds = _wide(red.translate(RED_HIGH), green.translate(UNDER_RED), blue.translate(UNDER_RED))
    greens = _wide(
        green.translate(GREEN_HIGH),
        red.translate(RED_LOW_FOR_GREEN),
        blue.translate(BLUE_LOW_FOR_GREEN),
    )
    blues = _wide(
        blue.translate(BLUE_HIGH),
        red.translate(RED_LOW_FOR_BLUE),
        green.translate(GREEN_LOW_FOR_BLUE),
    )
    return (reds * RED + greens * GREEN + blues * BLUE).to_bytes(width, "big")


def swatches(frame: Frame) -> Bars:
    """Find wide adjacent red, green and blue bars on every fourth row of an unmodified dump."""
    matched = 0
    for index in range(0, frame.height, ROW_STRIDE):
        if BARS.search(_classes(frame.row(index), frame.width)) is not None:
            matched += 1
    return Bars(width=frame.width, height=frame.height, matched_rows=matched)


def _changed_pixels(first: bytes, second: bytes) -> int:
    """Pixels with a channel that moved by the threshold, looked at only where a byte differs."""
    differing = (int.from_bytes(first, "big") ^ int.from_bytes(second, "big")).to_bytes(
        len(first), "big"
    )
    counted = 0
    next_pixel = 0
    for span in DIFFERING.finditer(differing):
        start = max(span.start() // CHANNELS, next_pixel)
        stop = (span.end() - 1) // CHANNELS + 1
        for pixel in range(start, stop):
            offset = pixel * CHANNELS
            moved = max(
                abs(first[offset + channel] - second[offset + channel])
                for channel in range(CHANNELS)
            )
            if moved >= CHANGE:
                counted += 1
        next_pixel = stop
    return counted


def surface_change(before: Frame, after: Frame) -> SurfaceChange:
    """Count the pixels that changed below the top bar, so a clock tick cannot pass."""
    if (before.width, before.height) != (after.width, after.height):
        raise errors.Refusal(
            refusals.RefusalReason.SCREEN_SIZE_CHANGED,
            subject=f"{before.width}x{before.height} then {after.width}x{after.height}",
            remedy="capture both frames from one display configuration",
        )
    changed = 0
    for index in range(min(TOP_BAR_ROWS, before.height), before.height):
        first, second = before.row(index), after.row(index)
        if first != second:
            changed += _changed_pixels(first.tobytes(), second.tobytes())
    minimum = max(MINIMUM_CHANGED, before.width * before.height // CHANGED_SHARE)
    return SurfaceChange(changed_pixels=changed, minimum_pixels=minimum)

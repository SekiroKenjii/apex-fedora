"""The screen judgements over rows, held to a pixel-by-pixel reading of the same rules."""

from __future__ import annotations

import random

import pytest

from apex.kernel import errors, refusals
from apex.model import screens

RED = b"\xe6\x26\x26"
GREEN = b"\x26\xbf\x40"
BLUE = b"\x26\x4c\xe6"
BLACK = b"\x00\x00\x00"
GREY = b"\x40\x40\x40"


def frame(width: int, height: int, rows: bytes) -> screens.Frame:
    return screens.Frame.parse(b"P6\n%d %d\n255\n" % (width, height) + rows)


def bars(red: int = 100, green: int = 100, blue: int = 100, gap: int = 0) -> bytes:
    return RED * red + BLACK * gap + GREEN * green + BLACK * gap + BLUE * blue


def test_three_wide_adjacent_bars_are_found_on_every_fourth_row() -> None:
    row = bars()
    payload = b"P6\n300 100\n255\n" + row * 100

    found = screens.swatches(screens.Frame.parse(payload))

    assert found.matched_rows == 25 and found.visible
    document = found.document()
    assert (document["width"], document["height"]) == (300, 100)
    assert document["matched_rows_at_stride_four"] == 25


@pytest.mark.parametrize(
    "row,reason",
    [
        (BLACK * 300, "blank"),
        (bars(red=79, green=111, blue=110), "a narrow bar"),
        (bars(gap=5) + BLACK * 0, "gaps wider than four pixels"),
        (GREEN * 100 + RED * 100 + BLUE * 100, "the wrong order"),
        (RED * 100 + GREEN * 100 + BLACK * 100, "only two bars"),
    ],
)
def test_anything_short_of_the_three_bars_is_not_visible(row: bytes, reason: str) -> None:
    width = len(row) // 3

    found = screens.swatches(frame(width, 100, row * 100))

    assert not found.visible, reason


def test_a_gap_of_four_pixels_between_bars_is_still_the_probe() -> None:
    row = bars(gap=4)
    payload = b"P6\n%d 100\n255\n" % (len(row) // 3) + row * 100

    found = screens.swatches(screens.Frame.parse(payload))

    assert found.visible and found.matched_rows == 25


def test_a_pixel_of_another_class_inside_a_gap_breaks_the_run() -> None:
    row = RED * 100 + BLUE * 1 + GREEN * 100 + BLUE * 100

    assert not screens.swatches(frame(301, 100, row * 100)).visible


def test_fewer_than_twenty_matching_rows_are_not_visible() -> None:
    rows = bars() * 76 + BLACK * 300 * 24

    found = screens.swatches(frame(300, 100, rows))

    assert found.matched_rows == 19 and not found.visible


@pytest.mark.parametrize("changed_rows,passes", [(0, False), (40, False), (41, False), (80, True)])
def test_a_shell_change_rejects_a_clock_tick_and_small_changes(
    changed_rows: int, passes: bool
) -> None:
    header = b"P6\n300 100\n255\n"
    before = header + BLACK * 300 * 100
    after = header + GREY * 300 * changed_rows + BLACK * 300 * (100 - changed_rows)

    found = screens.surface_change(screens.Frame.parse(before), screens.Frame.parse(after))

    assert found.visible is passes
    assert found.minimum_pixels == 5000
    assert found.changed_pixels == max(0, changed_rows - 40) * 300
    assert found.document()["visual_identification"] == "NOT TESTED"


def test_a_change_under_the_threshold_and_a_pixel_moved_in_two_channels_count_as_before() -> None:
    before = frame(3, 41, BLACK * 3 * 41)
    last = b"\x13\x00\x00" + b"\x14\x14\x00" + b"\x00\x00\x00"
    after = frame(3, 41, BLACK * 3 * 40 + last)

    found = screens.surface_change(before, after)

    assert found.changed_pixels == 1


def test_changed_dimensions_are_a_broken_capture_not_a_judgement() -> None:
    with pytest.raises(errors.Refusal) as caught:
        screens.surface_change(frame(1, 1, BLACK), frame(2, 1, BLACK * 2))

    assert caught.value.reason is refusals.RefusalReason.SCREEN_SIZE_CHANGED


@pytest.mark.parametrize(
    "payload",
    [
        b"P5\n1 1\n255\n\x00",
        b"P6\n1\n255\n\x00\x00\x00",
        b"P6\n1 1\n65535\n\x00\x00\x00",
        b"P6\n0 1\n255\n",
        b"P6\n2 1\n255\n\x00\x00\x00",
        b"",
    ],
)
def test_a_frame_that_is_not_a_binary_ppm_is_refused(payload: bytes) -> None:
    with pytest.raises(errors.Refusal) as caught:
        screens.Frame.parse(payload)

    assert caught.value.reason is refusals.RefusalReason.MALFORMED_SCREEN_FRAME


def classify(r: int, g: int, b: int) -> str | None:
    if r > 180 and g < 90 and b < 90:
        return "r"
    if g > 140 and r < 100 and b < 120:
        return "g"
    if b > 180 and r < 100 and g < 120:
        return "b"
    return None


def runs_of(width: int, row: bytes) -> list[tuple[str, int, int]]:
    runs: list[tuple[str, int, int]] = []
    current: str | None = None
    start = 0
    for x in range(width):
        color = classify(*row[x * 3:x * 3 + 3])
        if color != current:
            if current:
                runs.append((current, start, x))
            current, start = color, x
    if current:
        runs.append((current, start, width))
    return runs


def has_bars(runs: list[tuple[str, int, int]]) -> bool:
    for a, b, c in zip(runs, runs[1:], runs[2:], strict=False):
        ordered = (a[0], b[0], c[0]) == ("r", "g", "b")
        wide = min(end - begin for _, begin, end in (a, b, c)) >= 80
        if ordered and wide and b[1] - a[2] <= 4 and c[1] - b[2] <= 4:
            return True
    return False


def reference_swatches(width: int, height: int, data: bytes) -> int:
    stride = width * 3
    return sum(
        has_bars(runs_of(width, data[y * stride:(y + 1) * stride])) for y in range(0, height, 4)
    )


def reference_change(width: int, height: int, first: bytes, second: bytes) -> int:
    begin = min(40, height) * width * 3
    return sum(
        max(abs(a - b) for a, b in zip(first[i:i + 3], second[i:i + 3], strict=True)) >= 20
        for i in range(begin, len(first), 3)
    )


def test_both_judgements_agree_with_a_pixel_by_pixel_reading_on_random_frames() -> None:
    generator = random.Random(19)
    palette = [RED, GREEN, BLUE, BLACK, GREY, b"\xff\xff\xff", b"\x60\xc0\x80", b"\xb5\x59\x59"]
    for _ in range(40):
        width, height = generator.randint(1, 260), generator.randint(1, 50)
        first = b"".join(generator.choice(palette) for _ in range(width * height))
        noise = b"".join(
            bytes(generator.randint(0, 255) for _ in range(3)) if generator.random() < 0.3
            else first[i * 3:i * 3 + 3]
            for i in range(width * height)
        )
        before, after = frame(width, height, first), frame(width, height, noise)

        assert screens.swatches(before).matched_rows == reference_swatches(width, height, first)
        assert screens.surface_change(before, after).changed_pixels == reference_change(
            width, height, first, noise
        )

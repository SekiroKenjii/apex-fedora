"""Bounded memory over hostile input is a safety property, not an optimisation."""

from __future__ import annotations

import pytest

from apex.kernel import bounded, errors


def test_the_capture_limit_matches_what_the_guest_probes_already_use() -> None:
    assert bounded.CAPTURE_LIMIT.value == 262144


def test_text_within_the_limit_is_returned_whole() -> None:
    result = bounded.take(b"hello", bounded.Limit(10))

    assert result.data == b"hello"
    assert not result.truncated


def test_text_beyond_the_limit_is_cut_and_says_so() -> None:
    result = bounded.take(b"x" * 20, bounded.Limit(5))

    assert result.data == b"x" * 5
    assert result.truncated


def test_a_ring_buffer_keeps_the_tail_and_reports_the_loss() -> None:
    buffer = bounded.BoundedRingBuffer(bounded.Limit(4))

    buffer.append(b"abcdef")

    assert buffer.tail() == b"cdef"
    assert buffer.dropped == 2


def test_a_ring_buffer_that_never_overflows_reports_no_loss() -> None:
    buffer = bounded.BoundedRingBuffer(bounded.Limit(8))

    buffer.append(b"abc")
    buffer.append(b"de")

    assert buffer.tail() == b"abcde"
    assert buffer.dropped == 0


def test_a_zero_limit_is_refused() -> None:
    with pytest.raises(errors.Refusal):
        bounded.Limit(0)


def test_lines_are_yielded_up_to_the_line_limit() -> None:
    lines = list(bounded.bounded_lines(b"one\ntwo\nthree\n", bounded.Limit(3), maximum_lines=2))

    assert lines == [b"one", b"two"]


def test_a_line_longer_than_its_limit_is_refused() -> None:
    with pytest.raises(errors.Refusal):
        list(bounded.bounded_lines(b"a-very-long-line\n", bounded.Limit(4), maximum_lines=10))

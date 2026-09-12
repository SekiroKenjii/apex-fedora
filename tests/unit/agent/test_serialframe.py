"""One framing codec for guest output, shared by the side that writes and the side that reads.

The decoder is a state machine over lines with bounded memory, so a guest that writes
anything at all cannot make the host hold more than a frame's worth of it.
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from apex.agent import serialframe
from apex.config import defaults
from apex.kernel import bounded, errors, identifiers, refusals
from apexlib import installerlogs as older

TOKEN = identifiers.Token("a" * 32)
OTHER = identifiers.Token("b" * 32)
BUNDLE = json.dumps({"schema": 1, "token": str(TOKEN), "payload": {"x": 1}}).encode()


def test_a_payload_round_trips_through_the_frames() -> None:
    lines = serialframe.encode(BUNDLE, token=TOKEN)

    assert serialframe.decode_lines(lines, token=TOKEN) == BUNDLE


def test_every_chunk_is_at_most_the_declared_chunk_size() -> None:
    lines = serialframe.encode(b"x" * 10_000, token=TOKEN)

    for line in lines[:-1]:
        assert len(line.split(b":")[3]) <= defaults.SERIAL_CHUNK.value


def test_the_trailer_carries_the_count_and_the_digest() -> None:
    lines = serialframe.encode(BUNDLE, token=TOKEN)
    fields = lines[-1].split(b":")

    assert fields[0] == b"APEXEND"
    assert int(fields[2]) == len(lines) - 1
    assert fields[3].decode() == hashlib.sha256(BUNDLE).hexdigest()


def test_noise_between_frames_is_ignored() -> None:
    lines = serialframe.encode(BUNDLE, token=TOKEN)
    noisy = [b"[    3.2] kernel: something", lines[0], b"\x1b[0m", *lines[1:], b"login:"]

    assert serialframe.decode_lines(noisy, token=TOKEN) == BUNDLE


def test_frames_for_another_token_are_not_ours() -> None:
    lines = serialframe.encode(BUNDLE, token=OTHER)

    with pytest.raises(errors.Refusal) as raised:
        serialframe.decode_lines(lines, token=TOKEN)

    assert raised.value.reason is refusals.RefusalReason.FRAME_INCOMPLETE


def test_a_missing_chunk_is_out_of_order() -> None:
    lines = serialframe.encode(b"y" * 3000, token=TOKEN)
    del lines[1]

    with pytest.raises(errors.Refusal) as raised:
        serialframe.decode_lines(lines, token=TOKEN)

    assert raised.value.reason is refusals.RefusalReason.FRAME_OUT_OF_ORDER


def test_a_changed_chunk_fails_the_digest() -> None:
    lines = serialframe.encode(BUNDLE, token=TOKEN)
    prefix, _, chunk = lines[0].rpartition(b":")
    lines[0] = prefix + b":" + base64.b64encode(b"tampered payload of the same length")

    with pytest.raises(errors.Refusal) as raised:
        serialframe.decode_lines(lines, token=TOKEN)

    assert raised.value.reason in {
        refusals.RefusalReason.FRAME_CHECKSUM_MISMATCH,
        refusals.RefusalReason.FRAME_MALFORMED,
    }


def test_a_chunk_wider_than_the_declared_size_is_malformed() -> None:
    wide = b"APEXLOG:" + str(TOKEN).encode() + b":0:" + b"A" * (defaults.SERIAL_CHUNK.value + 4)

    with pytest.raises(errors.Refusal) as raised:
        serialframe.decode_lines([wide], token=TOKEN)

    assert raised.value.reason is refusals.RefusalReason.FRAME_MALFORMED


def test_a_trailer_without_chunks_is_incomplete() -> None:
    trailer = b"APEXEND:" + str(TOKEN).encode() + b":0:" + b"0" * 64

    with pytest.raises(errors.Refusal) as raised:
        serialframe.decode_lines([trailer], token=TOKEN)

    assert raised.value.reason is refusals.RefusalReason.FRAME_INCOMPLETE


def test_the_decoder_holds_no_more_than_a_line_of_noise() -> None:
    decoder = serialframe.FrameDecoder(token=TOKEN)

    for _ in range(64):
        assert decoder.feed(b"z" * 65_536) is None

    assert decoder.pending_bytes <= serialframe.LINE_LIMIT.value


def test_a_payload_over_the_transfer_limit_is_refused_as_it_streams() -> None:
    decoder = serialframe.FrameDecoder(token=TOKEN, limit=bounded.Limit(1024))
    lines = serialframe.encode(b"q" * 4096, token=TOKEN)

    with pytest.raises(errors.Refusal) as raised:
        for line in lines:
            decoder.feed(line + b"\n")

    assert raised.value.reason is refusals.RefusalReason.FRAME_LIMIT_EXCEEDED


def test_the_streaming_decoder_returns_the_payload_once_the_trailer_arrives() -> None:
    decoder = serialframe.FrameDecoder(token=TOKEN)
    stream = b"\r\n".join(serialframe.encode(BUNDLE, token=TOKEN)) + b"\r\n"

    seen = [decoder.feed(stream[index : index + 7]) for index in range(0, len(stream), 7)]

    assert [item for item in seen if item is not None] == [BUNDLE]


def test_the_older_decoder_reads_what_the_new_encoder_writes() -> None:
    lines = serialframe.encode(BUNDLE, token=TOKEN)

    assert older.decode([line + b"\n" for line in lines], str(TOKEN)) == json.loads(BUNDLE)

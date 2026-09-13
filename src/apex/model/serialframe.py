"""One framing codec for guest output, used by the side that writes and the side that reads.

A payload is base64, cut into chunks of the shared size, each on its own line with the token
and an index, and closed by a trailer carrying the count and the digest. The decoder is a
state machine over lines with bounded memory: it keeps at most one line of unread bytes, so a
guest that writes anything at all cannot make the reader hold more than a frame of it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
import re

from apex.kernel import bounded, errors, identifiers, refusals

CHUNK_PREFIX = b"APEXLOG"
TRAILER_PREFIX = b"APEXEND"
SEPARATOR = b":"
LINE_LIMIT = bounded.Limit(1024)
TRANSFER_LIMIT = bounded.Limit(16 * 1024 * 1024)
INDEX_DIGITS = 6
_CHUNK_TEXT = re.compile(rb"[A-Za-z0-9+/=]+")
_INDEX_TEXT = re.compile(rb"[0-9]{1,%d}" % INDEX_DIGITS)
_DIGEST_TEXT = re.compile(rb"[0-9a-f]{64}")


def encode(payload: bytes, *, token: identifiers.Token) -> list[bytes]:
    encoded = base64.b64encode(payload)
    width = bounded.SERIAL_CHUNK.value
    chunks = [encoded[start : start + width] for start in range(0, len(encoded), width)]
    name = str(token).encode()
    lines = [
        SEPARATOR.join((CHUNK_PREFIX, name, str(index).encode(), chunk))
        for index, chunk in enumerate(chunks)
    ]
    digest = hashlib.sha256(payload).hexdigest().encode()
    lines.append(SEPARATOR.join((TRAILER_PREFIX, name, str(len(chunks)).encode(), digest)))
    return lines


class FrameDecoder:
    """Feed it bytes as they arrive. It answers with the payload once, when the trailer holds."""

    def __init__(self, *, token: identifiers.Token, limit: bounded.Limit = TRANSFER_LIMIT) -> None:
        name = str(token).encode()
        self._chunk_prefix = SEPARATOR.join((CHUNK_PREFIX, name)) + SEPARATOR
        self._trailer_prefix = SEPARATOR.join((TRAILER_PREFIX, name)) + SEPARATOR
        self._encoded_limit = math.ceil(limit.value / 3) * 4
        self._buffer = bytearray()
        self._chunks: list[bytes] = []
        self._encoded_size = 0
        self._payload: bytes | None = None

    @property
    def pending_bytes(self) -> int:
        return len(self._buffer)

    def feed(self, data: bytes) -> bytes | None:
        if self._payload is not None:
            return None
        self._buffer.extend(data)
        while True:
            newline = self._buffer.find(b"\n")
            if newline < 0:
                self._drop_noise()
                return None
            line = bytes(self._buffer[:newline]).rstrip(b"\r")
            del self._buffer[: newline + 1]
            payload = self._consume(line)
            if payload is not None:
                self._payload = payload
                return payload

    def _drop_noise(self) -> None:
        excess = len(self._buffer) - LINE_LIMIT.value
        if excess > 0:
            del self._buffer[:excess]

    def _consume(self, line: bytes) -> bytes | None:
        if line.startswith(self._chunk_prefix):
            self._chunk(line[len(self._chunk_prefix) :])
            return None
        if line.startswith(self._trailer_prefix):
            return self._finish(line[len(self._trailer_prefix) :])
        return None

    def _chunk(self, rest: bytes) -> None:
        index_text, _, chunk = rest.partition(SEPARATOR)
        if (
            not _INDEX_TEXT.fullmatch(index_text)
            or not _CHUNK_TEXT.fullmatch(chunk)
            or len(chunk) > bounded.SERIAL_CHUNK.value
        ):
            raise errors.Refusal(refusals.RefusalReason.FRAME_MALFORMED, subject="chunk line")
        index = int(index_text)
        if index != len(self._chunks):
            raise errors.Refusal(
                refusals.RefusalReason.FRAME_OUT_OF_ORDER,
                subject=f"chunk {index} arrived after {len(self._chunks)} chunks",
            )
        self._encoded_size += len(chunk)
        if self._encoded_size > self._encoded_limit:
            raise errors.Refusal(
                refusals.RefusalReason.FRAME_LIMIT_EXCEEDED,
                subject=f"{self._encoded_size} encoded bytes",
                remedy="the guest is sending more than the transfer limit allows",
            )
        self._chunks.append(chunk)

    def _finish(self, rest: bytes) -> bytes:
        count_text, _, digest = rest.partition(SEPARATOR)
        if not _INDEX_TEXT.fullmatch(count_text) or not _DIGEST_TEXT.fullmatch(digest):
            raise errors.Refusal(refusals.RefusalReason.FRAME_MALFORMED, subject="trailer line")
        count = int(count_text)
        if count == 0 or count != len(self._chunks):
            raise errors.Refusal(
                refusals.RefusalReason.FRAME_INCOMPLETE,
                subject=f"trailer counts {count}, {len(self._chunks)} chunks arrived",
            )
        try:
            payload = base64.b64decode(b"".join(self._chunks), validate=True)
        except (binascii.Error, ValueError) as fault:
            raise errors.Refusal(
                refusals.RefusalReason.FRAME_MALFORMED, subject="payload is not base64"
            ) from fault
        if hashlib.sha256(payload).hexdigest().encode() != digest:
            raise errors.Refusal(
                refusals.RefusalReason.FRAME_CHECKSUM_MISMATCH, subject="payload digest"
            )
        return payload


def decode_lines(
    lines: list[bytes], *, token: identifiers.Token, limit: bounded.Limit = TRANSFER_LIMIT
) -> bytes:
    decoder = FrameDecoder(token=token, limit=limit)
    for line in lines:
        payload = decoder.feed(line + b"\n")
        if payload is not None:
            return payload
    raise errors.Refusal(
        refusals.RefusalReason.FRAME_INCOMPLETE,
        subject="no trailer arrived",
        remedy="the guest did not finish writing; do not act on what arrived",
    )

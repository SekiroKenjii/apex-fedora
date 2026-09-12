"""Sharing extents: identical bytes share, differing bytes are an outcome, a range is aligned.

The real call needs a filesystem that supports it. Where the temporary directory does not,
the real adapter must say so as a port failure rather than answer as if it had shared.
"""

from __future__ import annotations

import pytest

from apex.kernel import errors, quantities, safepaths
from apex.model import extents
from apex.ports import extents as extent_port


def written(root: safepaths.RuntimeRoot, name: str, payload: bytes) -> safepaths.SafePath:
    target = root.path / name
    target.write_bytes(payload)
    return safepaths.SafePath.regular_file(target, within=root)


def test_identical_bytes_share_or_the_filesystem_declines(
    shares: extent_port.ExtentPort, root: safepaths.RuntimeRoot
) -> None:
    payload = bytes(range(256)) * 16
    source = written(root, "source", payload)
    target = written(root, "target", payload)

    try:
        outcome = shares.share(source, target, extents.DedupeRange(0, len(payload)))
    except errors.PortFailure as failure:
        pytest.skip(f"NOT TESTED: {failure.cause}")

    assert outcome.complete
    assert outcome.bytes_deduped == len(payload)
    assert target.path.read_bytes() == payload


def test_differing_bytes_are_reported_not_shared(
    shares: extent_port.ExtentPort, root: safepaths.RuntimeRoot
) -> None:
    payload = bytes(range(256)) * 16
    source = written(root, "source", payload)
    target = written(root, "target", bytes([payload[0] ^ 1]) + payload[1:])

    try:
        outcome = shares.share(source, target, extents.DedupeRange(0, len(payload)))
    except errors.PortFailure as failure:
        pytest.skip(f"NOT TESTED: {failure.cause}")

    assert outcome.differed
    assert target.path.read_bytes() != payload


def test_a_misaligned_range_is_refused_before_any_call(
    shares: extent_port.ExtentPort, root: safepaths.RuntimeRoot
) -> None:
    with pytest.raises(errors.Refusal):
        extents.DedupeRange(1, quantities.Mib(1).bytes)

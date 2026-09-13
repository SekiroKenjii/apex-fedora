"""The builder's base image is a reviewed lock: read where it lies, refused when malformed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.config import builderpins
from apex.kernel import errors, refusals, safepaths

REPOSITORY = Path(__file__).resolve().parents[3]


def test_the_reviewed_base_image_is_pinned_by_digest_under_https() -> None:
    reviewed = builderpins.load(safepaths.SourceRoot.adopt(REPOSITORY))

    assert str(reviewed.source.filename) == "builder-base.qcow2"
    assert str(reviewed.source.url).startswith("https://")
    assert str(reviewed.source.url).endswith(".qcow2")
    assert len(reviewed.source.sha256.hex) == 64
    assert json.loads(reviewed.document)["base_image"]["sha256"] == reviewed.source.sha256.hex


@pytest.mark.parametrize(
    "payload,reason",
    [
        (None, refusals.RefusalReason.LOCK_MISSING),
        (b"{", refusals.RefusalReason.LOCK_UNREADABLE),
        (b'{"schema": 2}', refusals.RefusalReason.LOCK_SCHEMA_UNSUPPORTED),
        (b'{"schema": 1}', refusals.RefusalReason.LOCK_ENTRY_MALFORMED),
        (
            b'{"schema": 1, "base_image": {"url": "https://x/y", "sha256": "ab"}}',
            refusals.RefusalReason.LOCK_CHECKSUM_MALFORMED,
        ),
    ],
)
def test_a_lock_that_is_absent_unreadable_or_malformed_is_refused(
    tmp_path: Path, payload: bytes | None, reason: refusals.RefusalReason
) -> None:
    (tmp_path / "config").mkdir()
    if payload is not None:
        (tmp_path / builderpins.LOCK_PATH).write_bytes(payload)

    with pytest.raises(errors.Refusal) as caught:
        builderpins.load(safepaths.SourceRoot.adopt(tmp_path))

    assert caught.value.reason is reason

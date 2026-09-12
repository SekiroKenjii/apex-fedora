"""The reviewed fingerprint test lock is read from the checkout and never recreated."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.config import fingerprintpins
from apex.kernel import errors, refusals, safepaths

REPOSITORY = Path(__file__).resolve().parents[3]


def test_the_reviewed_lock_in_this_repository_loads() -> None:
    loaded = fingerprintpins.load(safepaths.SourceRoot.adopt(REPOSITORY))

    assert len(loaded.files.files) == 3
    assert json.loads(loaded.document) == json.loads(
        (REPOSITORY / fingerprintpins.LOCK_PATH).read_text()
    )


def test_a_missing_lock_is_refused_not_recreated(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)

    with pytest.raises(errors.Refusal) as raised:
        fingerprintpins.load(safepaths.SourceRoot.adopt(project))

    assert raised.value.reason is refusals.RefusalReason.LOCK_MISSING
    assert not (project / fingerprintpins.LOCK_PATH).exists()


def test_a_lock_that_is_a_link_is_refused(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    (project / fingerprintpins.LOCK_PATH).symlink_to(REPOSITORY / fingerprintpins.LOCK_PATH)

    with pytest.raises(errors.Refusal) as raised:
        fingerprintpins.load(safepaths.SourceRoot.adopt(project))

    assert raised.value.reason is refusals.RefusalReason.PATH_IS_A_SYMLINK

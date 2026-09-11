"""The reviewed source lock is read from the checkout and never recreated."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from apex.config import sourcepins
from apex.kernel import errors, refusals, safepaths

REPOSITORY = Path(__file__).resolve().parents[3]


def checkout(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    return project


def test_the_reviewed_lock_in_this_repository_loads() -> None:
    loaded = sourcepins.load(safepaths.SourceRoot.adopt(REPOSITORY))

    assert len(loaded.lock.sources) == 6
    assert json.loads(loaded.document) == json.loads(
        (REPOSITORY / sourcepins.LOCK_PATH).read_text()
    )


def test_a_missing_lock_is_refused_not_recreated(tmp_path: Path) -> None:
    project = checkout(tmp_path)

    with pytest.raises(errors.Refusal) as raised:
        sourcepins.load(safepaths.SourceRoot.adopt(project))

    assert raised.value.reason is refusals.RefusalReason.LOCK_MISSING
    assert not (project / sourcepins.LOCK_PATH).exists()


def test_a_malformed_lock_is_refused(tmp_path: Path) -> None:
    project = checkout(tmp_path)
    (project / sourcepins.LOCK_PATH).write_text("{unfinished")

    with pytest.raises(errors.Refusal) as raised:
        sourcepins.load(safepaths.SourceRoot.adopt(project))

    assert raised.value.reason is refusals.RefusalReason.LOCK_UNREADABLE


def test_a_symlinked_lock_is_refused(tmp_path: Path) -> None:
    project = checkout(tmp_path)
    elsewhere = tmp_path / "outside.json"
    elsewhere.write_text((REPOSITORY / sourcepins.LOCK_PATH).read_text())
    (project / sourcepins.LOCK_PATH).symlink_to(elsewhere)

    with pytest.raises(errors.Refusal) as raised:
        sourcepins.load(safepaths.SourceRoot.adopt(project))

    assert raised.value.reason is refusals.RefusalReason.PATH_IS_A_SYMLINK


def test_a_lock_with_a_bad_entry_is_refused_by_its_own_reason(tmp_path: Path) -> None:
    project = checkout(tmp_path)
    document = json.loads((REPOSITORY / sourcepins.LOCK_PATH).read_text())
    document["sources"]["shadcn-gnome"]["url"] = "http://insecure.invalid/x.tar.gz"
    (project / sourcepins.LOCK_PATH).write_text(json.dumps(document))

    with pytest.raises(errors.Refusal) as raised:
        sourcepins.load(safepaths.SourceRoot.adopt(project))

    assert raised.value.reason is refusals.RefusalReason.URL_NOT_HTTPS

"""Which version of the store is on disk, as a value rather than a branch.

The mark's absence means version one. That rule invites one specific accident: a mark that
exists but cannot be read looks like a mark that is not there, and the oldest reader claims a
store it does not understand. So absence and corruption are separate inhabitants, and only
one of them elects a reader.
"""

from __future__ import annotations

import json
from pathlib import Path

from apex.model import storemark


def inventory(root: Path) -> set[tuple[str, int]]:
    return {(str(item.relative_to(root)), item.stat().st_mode) for item in root.rglob("*")}


def test_a_root_with_no_mark_reads_as_unmarked(tmp_path: Path) -> None:
    assert storemark.read_mark(tmp_path) == storemark.Unmarked()


def test_a_mark_that_will_not_parse_reads_as_unreadable_rather_than_as_version_one(
    tmp_path: Path,
) -> None:
    (tmp_path / storemark.MARK_NAME).write_text("{ truncated")

    mark = storemark.read_mark(tmp_path)

    assert isinstance(mark, storemark.Unreadable)
    assert mark != storemark.Unmarked()


def test_a_symlinked_mark_is_refused_before_it_is_followed(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.json"
    elsewhere.write_text(json.dumps({storemark.SCHEMA_KEY: 2}))
    (tmp_path / storemark.MARK_NAME).symlink_to(elsewhere)

    assert isinstance(storemark.read_mark(tmp_path), storemark.Unreadable)


def test_a_mark_larger_than_the_limit_is_unreadable_rather_than_truncated(
    tmp_path: Path,
) -> None:
    padding = " " * (storemark.MARK_BYTE_LIMIT + 1)
    (tmp_path / storemark.MARK_NAME).write_text(
        json.dumps({storemark.SCHEMA_KEY: 1, "note": padding})
    )

    assert isinstance(storemark.read_mark(tmp_path), storemark.Unreadable)


def test_a_mark_written_with_either_schema_or_version_reads_as_that_version(
    tmp_path: Path,
) -> None:
    for key in (storemark.SCHEMA_KEY, storemark.VERSION_KEY):
        (tmp_path / storemark.MARK_NAME).write_text(json.dumps({key: 4}))

        assert storemark.read_mark(tmp_path) == storemark.Marked(4)


def test_a_version_that_is_not_a_positive_integer_reads_as_unreadable(tmp_path: Path) -> None:
    for value in (0, -1, "1", 1.5, True, None, [1]):
        (tmp_path / storemark.MARK_NAME).write_text(json.dumps({storemark.SCHEMA_KEY: value}))

        assert isinstance(storemark.read_mark(tmp_path), storemark.Unreadable), value


def test_a_mark_that_is_not_an_object_reads_as_unreadable(tmp_path: Path) -> None:
    (tmp_path / storemark.MARK_NAME).write_text(json.dumps([1]))

    assert isinstance(storemark.read_mark(tmp_path), storemark.Unreadable)


def test_a_directory_where_the_mark_belongs_reads_as_unreadable(tmp_path: Path) -> None:
    (tmp_path / storemark.MARK_NAME).mkdir()

    assert isinstance(storemark.read_mark(tmp_path), storemark.Unreadable)


def test_reading_the_mark_creates_nothing(tmp_path: Path) -> None:
    (tmp_path / "evidence").mkdir()
    before = inventory(tmp_path)

    storemark.read_mark(tmp_path)

    assert inventory(tmp_path) == before

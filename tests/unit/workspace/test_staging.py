"""Reading rows, and refusing the two shapes that cannot be inspected."""

from __future__ import annotations

import pytest

from apex.kernel import errors, refusals, treerows
from apex.workspace import staging


def index(*records: bytes) -> bytes:
    return b"\0".join(records) + b"\0"


def test_an_index_row_carries_its_mode_object_and_path() -> None:
    rows = staging.index_rows(index(b"100644 abc123 0\tsrc/a.py"))

    assert rows[0].mode is treerows.EntryMode.REGULAR
    assert rows[0].object_name == "abc123"
    assert rows[0].path.value == "src/a.py"


def test_a_tree_row_reads_the_object_from_the_third_field() -> None:
    rows = staging.tree_rows(index(b"100755 blob def456\ttools/run.sh"))

    assert rows[0].mode is treerows.EntryMode.EXECUTABLE
    assert rows[0].object_name == "def456"


def test_an_unmerged_index_row_is_refused() -> None:
    with pytest.raises(errors.Refusal) as raised:
        staging.index_rows(index(b"100644 abc123 1\tsrc/a.py"))

    assert raised.value.reason is refusals.RefusalReason.REPOSITORY_INDEX_UNMERGED


def test_a_path_that_is_not_text_is_a_typed_refusal() -> None:
    """The code this replaces lets the decoding error escape with nothing behind it."""
    with pytest.raises(errors.Refusal) as raised:
        staging.index_rows(index(b"100644 abc123 0\t\xff\xfe.py"))

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_TREE_ROW


def test_an_unrecognised_mode_is_refused_rather_than_guessed_at() -> None:
    with pytest.raises(errors.Refusal) as raised:
        staging.index_rows(index(b"040000 abc123 0\tsrc"))

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_TREE_ROW


def test_an_empty_listing_is_no_rows() -> None:
    assert staging.index_rows(b"") == ()

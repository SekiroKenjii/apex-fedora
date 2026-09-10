"""Reading the rows Git reports, without deciding anything about them.

Two formats, one shape. The index lists a stage number that a tree listing does not, and an
unmerged row carries a stage above zero, which is a conflict rather than a thing to inspect.

A name that is not text is refused here with a reason. The code this replaces lets the decoding
error escape untyped, so the operator sees a refusal with nothing behind it.
"""

from __future__ import annotations

import dataclasses

from apex.kernel import errors, refusals, treerows

FIELD_SEPARATOR = b"\t"
ROW_SEPARATOR = b"\0"
MERGED_STAGE = "0"
FIELD_COUNT = 3


@dataclasses.dataclass(frozen=True, slots=True)
class Row:
    mode: treerows.EntryMode
    object_name: str
    path: treerows.RepoPath


def _decoded(name: bytes) -> str:
    try:
        return name.decode("utf-8")
    except UnicodeDecodeError as error:
        raise errors.Refusal(
            refusals.RefusalReason.MALFORMED_TREE_ROW,
            subject=repr(name),
            remedy="a tracked path is text",
        ) from error


def _row(meta: bytes, name: bytes, *, staged: bool) -> Row:
    fields = meta.decode("utf-8", errors="replace").split()
    if len(fields) < FIELD_COUNT:
        raise errors.Refusal(
            refusals.RefusalReason.MALFORMED_TREE_ROW, subject=repr(meta)
        )
    if staged and fields[2] != MERGED_STAGE:
        raise errors.Refusal(
            refusals.RefusalReason.REPOSITORY_INDEX_UNMERGED,
            subject=_decoded(name),
            remedy="resolve the conflict before committing",
        )
    return Row(
        mode=treerows.EntryMode.parse(fields[0]),
        object_name=fields[1] if staged else fields[2],
        path=treerows.RepoPath(_decoded(name)),
    )


def _rows(raw: bytes, *, staged: bool) -> tuple[Row, ...]:
    parsed = []
    for record in raw.split(ROW_SEPARATOR):
        if not record:
            continue
        meta, _, name = record.partition(FIELD_SEPARATOR)
        parsed.append(_row(meta, name, staged=staged))
    return tuple(parsed)


def index_rows(raw: bytes) -> tuple[Row, ...]:
    """Rows of `ls-files --stage -z`: mode, object, stage, then the path."""
    return _rows(raw, staged=True)


def tree_rows(raw: bytes) -> tuple[Row, ...]:
    """Rows of `ls-tree -rz`: mode, type, object, then the path."""
    return _rows(raw, staged=False)

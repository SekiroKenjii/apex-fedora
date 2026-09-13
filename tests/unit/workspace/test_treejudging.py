"""One tree's rows judged together: by path, mode and size, and by bytes only when read."""

from __future__ import annotations

from apex.config import defaults
from apex.kernel import quantities, treerows
from apex.workspace import gitguarding, staging, treejudging


def row(path: str, name: str, mode: treerows.EntryMode = treerows.EntryMode.REGULAR) -> staging.Row:
    return staging.Row(mode=mode, object_name=name, path=treerows.RepoPath(path))


def judge(
    rows: tuple[staging.Row, ...], sizes: dict[str, int], contents: dict[str, bytes]
) -> list[str]:
    findings = treejudging.judge_rows(
        rows,
        sizes={name: quantities.ByteCount(size) for name, size in sizes.items()},
        contents=contents,
        entry_rules=gitguarding.registered_entry_rules(),
        content_rules=gitguarding.registered_content_rules(),
    )
    return sorted(str(item.rule) for item in findings)


def test_a_permitted_source_file_with_plain_bytes_raises_no_finding() -> None:
    assert judge((row("src/a.py", "abc"),), {"abc": 9}, {"abc": b"value = 1\n"}) == []


def test_each_row_is_judged_by_what_the_rules_can_see() -> None:
    private = judge((row(".env", "abc"),), {"abc": 3}, {"abc": b"A=1"})
    link = judge((row("link", "abc", treerows.EntryMode.SYMLINK),), {}, {})
    too_large = judge(
        (row("blob.bin", "big"),), {"big": defaults.SOURCE_BLOB_LIMIT.value + 1}, {}
    )
    secret = judge(
        (row("notes.txt", "abc"),), {"abc": 30},
        {"abc": b"-----BEGIN " + b"PRIVATE KEY-----\nx\n"},
    )

    assert "repository.private-document" in private
    assert link == ["repository.entry-is-a-symlink"]
    assert too_large == ["repository.blob-too-large"]
    assert "repository.pem-private-key" in secret


def test_readable_names_each_small_blob_once_and_never_a_large_one_or_a_link() -> None:
    rows = (
        row("a.py", "small"),
        row("copy.py", "small"),
        row("big.bin", "big"),
        row("link", "small", treerows.EntryMode.SYMLINK),
    )
    sizes = {
        "small": quantities.ByteCount(10),
        "big": quantities.ByteCount(defaults.SOURCE_BLOB_LIMIT.value + 1),
    }

    assert treejudging.readable(rows, sizes) == ("small",)

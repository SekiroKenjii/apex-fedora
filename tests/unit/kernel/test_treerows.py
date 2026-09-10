"""How a git row is read before any rule looks at it.

The old guard reads a path with `PurePosixPath` and a mode with a set membership test. Both
carry behaviour that a decomposition could change without noticing, so both are pinned here.
"""

from __future__ import annotations

import pathlib

import pytest

from apex.kernel import errors, refusals, treerows


def test_a_backslash_path_is_one_component() -> None:
    """A backslash is an ordinary character in a name on this platform."""
    path = treerows.RepoPath("c:\\windows\\x")

    assert path.components == ("c:\\windows\\x",)
    assert path.name_lowered == "c:\\windows\\x"


def test_the_directory_components_exclude_the_name() -> None:
    path = treerows.RepoPath("a/logs/b.txt")

    assert path.directory_components == ("a", "logs")
    assert path.name_lowered == "b.txt"


def test_a_bare_name_has_no_directory_components() -> None:
    assert treerows.RepoPath("logs").directory_components == ()


def test_the_derived_values_match_the_parser_the_old_guard_uses() -> None:
    """Fidelity comes from delegating, not from reproducing the quirks by hand."""
    for raw in (".", "..", "./a.txt", "/a.txt", "/etc/passwd", "a/..", "a/./b.txt", "a//b"):
        parsed = pathlib.PurePosixPath(raw)
        path = treerows.RepoPath(raw)

        assert path.name_lowered == parsed.name.lower()
        assert path.suffix_lowered == parsed.suffix.lower()
        assert path.directory_components == parsed.parts[:-1]
        assert path.is_absolute == parsed.is_absolute()


def test_only_the_last_suffix_is_reported() -> None:
    assert treerows.RepoPath("x.tar.gz").suffix_lowered == ".gz"
    assert treerows.RepoPath("a.LOG").suffix_lowered == ".log"
    assert treerows.RepoPath("plain").suffix_lowered == ""


def test_traversal_and_absolute_paths_are_visible_to_a_rule() -> None:
    assert treerows.RepoPath("/a.txt").is_absolute
    assert treerows.RepoPath("a/../b.txt").traverses_upward
    assert not treerows.RepoPath("./a.txt").traverses_upward


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("100644", treerows.EntryMode.REGULAR),
        ("100755", treerows.EntryMode.EXECUTABLE),
        ("120000", treerows.EntryMode.SYMLINK),
        ("160000", treerows.EntryMode.GITLINK),
    ],
)
def test_every_recognised_mode_parses(raw: str, expected: treerows.EntryMode) -> None:
    assert treerows.EntryMode.parse(raw) is expected


def test_an_unrecognised_mode_is_a_typed_refusal() -> None:
    """Parsing must be total. A mode a rule has to guess about is a gap in the rule set."""
    with pytest.raises(errors.Refusal) as raised:
        treerows.EntryMode.parse("040000")

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_TREE_ROW


def test_only_the_two_file_modes_carry_a_blob() -> None:
    assert treerows.EntryMode.REGULAR.carries_blob
    assert treerows.EntryMode.EXECUTABLE.carries_blob
    assert not treerows.EntryMode.SYMLINK.carries_blob
    assert not treerows.EntryMode.GITLINK.carries_blob

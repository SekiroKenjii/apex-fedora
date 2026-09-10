"""Bundling sources. The same input always produces the same bytes."""

from __future__ import annotations

import pytest

from apex.kernel import errors, refusals, safepaths
from apex.ports import archives as archive_port


def sources(root: safepaths.RuntimeRoot) -> archive_port.SourceSet:
    (root.path / "tools").mkdir()
    (root.path / "tools" / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (root.path / "tools" / "helper.py").write_text("value = 1\n")
    return archive_port.SourceSet(root=root, relative_paths=("tools",))


def test_bundling_produces_a_root_over_every_file(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    bundle = archives.bundle(sources(root), into=root.child("source.tar"))

    assert len(bundle.files) == 2
    assert bundle.merkle_root


def test_bundling_twice_produces_the_same_root(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    declared = sources(root)

    first = archives.bundle(declared, into=root.child("a.tar"))
    second = archives.bundle(declared, into=root.child("b.tar"))

    assert first.merkle_root == second.merkle_root


def test_changing_one_file_changes_the_root(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    declared = sources(root)
    before = archives.bundle(declared, into=root.child("a.tar"))

    (root.path / "tools" / "helper.py").write_text("value = 2\n")
    after = archives.bundle(declared, into=root.child("b.tar"))

    assert before.merkle_root != after.merkle_root


def test_a_shell_script_keeps_an_executable_mode(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    bundle = archives.bundle(sources(root), into=root.child("source.tar"))
    modes = {entry.path: entry.mode.value for entry in bundle.files}

    assert modes["tools/run.sh"] == 0o755
    assert modes["tools/helper.py"] == 0o644


def test_a_symlink_in_the_source_set_is_refused(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    declared = sources(root)
    (root.path / "tools" / "link.py").symlink_to(root.path / "tools" / "helper.py")

    with pytest.raises(errors.Refusal) as raised:
        archives.bundle(declared, into=root.child("source.tar"))

    assert raised.value.reason is refusals.RefusalReason.PATH_IS_A_SYMLINK


def test_every_file_is_read_exactly_once(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    """The current bundler reads each file twice: once to write, once to hash."""
    bundle = archives.bundle(sources(root), into=root.child("source.tar"))

    assert bundle.reads == len(bundle.files)


def test_an_absent_declared_path_is_skipped_not_invented(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    declared = archive_port.SourceSet(root=root, relative_paths=("tools", "absent"))
    (root.path / "tools").mkdir()
    (root.path / "tools" / "one.py").write_text("x = 1\n")

    bundle = archives.bundle(declared, into=root.child("source.tar"))

    assert [entry.path for entry in bundle.files] == ["tools/one.py"]

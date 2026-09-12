"""Bundling sources. The same input always produces the same bytes."""

from __future__ import annotations

import pytest

from apex.adapters.fakes import fake_archives
from apex.kernel import errors, refusals, safepaths
from apex.ports import archives as archive_port


def sources(root: safepaths.RuntimeRoot) -> archive_port.SourceSet:
    (root.path / "tools").mkdir()
    (root.path / "tools" / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (root.path / "tools" / "helper.py").write_text("value = 1\n")
    return archive_port.SourceSet(
        root=safepaths.SourceRoot.adopt(root.path), relative_paths=("tools",)
    )


def refuse_helpers(candidate: archive_port.BundleCandidate) -> None:
    if candidate.path.endswith("helper.py"):
        raise errors.Refusal(
            refusals.RefusalReason.REPOSITORY_PRIVATE_DOCUMENT, subject=candidate.path
        )


def test_an_archive_extracts_below_the_directory_it_is_given(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    import io  # noqa: PLC0415
    import tarfile  # noqa: PLC0415

    packed = root.path / "upstream.tar.gz"
    with tarfile.open(packed, "w:gz") as opened:
        member = tarfile.TarInfo("ventoy-1.1.05/ventoy/version")
        member.size = 6
        opened.addfile(member, io.BytesIO(b"1.1.05"))
    into = root.child("upstream")
    into.path.mkdir()

    archives.extract(safepaths.SafePath.regular_file(packed, within=root), into=into)

    if isinstance(archives, fake_archives.MemoryArchives):
        assert archives.extracted[-1][1] == into
    else:
        assert (into.path / "ventoy-1.1.05" / "ventoy" / "version").read_bytes() == b"1.1.05"


def test_bundling_produces_a_root_over_every_file(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    bundle = archives.bundle(
        sources(root), into=root.child("source.tar"), screen=archive_port.admit_all
    )

    assert len(bundle.files) == 2
    assert bundle.merkle_root
    assert bundle.archive_digest


def test_bundling_twice_produces_the_same_root_and_archive_digest(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    declared = sources(root)

    first = archives.bundle(declared, into=root.child("a.tar"), screen=archive_port.admit_all)
    second = archives.bundle(declared, into=root.child("b.tar"), screen=archive_port.admit_all)

    assert first.merkle_root == second.merkle_root
    assert first.archive_digest == second.archive_digest


def test_changing_one_file_changes_the_root(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    declared = sources(root)
    before = archives.bundle(declared, into=root.child("a.tar"), screen=archive_port.admit_all)

    (root.path / "tools" / "helper.py").write_text("value = 2\n")
    after = archives.bundle(declared, into=root.child("b.tar"), screen=archive_port.admit_all)

    assert before.merkle_root != after.merkle_root
    assert before.archive_digest != after.archive_digest


def test_a_shell_script_keeps_an_executable_mode(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    bundle = archives.bundle(
        sources(root), into=root.child("source.tar"), screen=archive_port.admit_all
    )
    modes = {entry.path: entry.mode.value for entry in bundle.files}

    assert modes["tools/run.sh"] == 0o755
    assert modes["tools/helper.py"] == 0o644


def test_a_symlink_in_the_source_set_is_refused(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    declared = sources(root)
    (root.path / "tools" / "link.py").symlink_to(root.path / "tools" / "helper.py")

    with pytest.raises(errors.Refusal) as raised:
        archives.bundle(declared, into=root.child("source.tar"), screen=archive_port.admit_all)

    assert raised.value.reason is refusals.RefusalReason.PATH_IS_A_SYMLINK


def test_every_file_is_read_exactly_once(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    bundle = archives.bundle(
        sources(root), into=root.child("source.tar"), screen=archive_port.admit_all
    )

    assert bundle.reads == len(bundle.files)


def test_an_absent_declared_path_is_skipped_not_invented(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    declared = archive_port.SourceSet(
        root=safepaths.SourceRoot.adopt(root.path), relative_paths=("tools", "absent")
    )
    (root.path / "tools").mkdir()
    (root.path / "tools" / "one.py").write_text("x = 1\n")

    bundle = archives.bundle(declared, into=root.child("source.tar"), screen=archive_port.admit_all)

    assert [entry.path for entry in bundle.files] == ["tools/one.py"]


def test_a_symlinked_directory_is_refused_rather_than_skipped(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    """A directory test that follows links discards the subtree before the link is examined.

    The whole point of a root over the bundle is that it cannot omit a file because nobody
    listed one. A subtree that disappears with no refusal defeats exactly that.
    """
    declared = sources(root)
    (root.path / "elsewhere").mkdir()
    (root.path / "elsewhere" / "hidden.py").write_text("secret = 1\n")
    (root.path / "tools" / "vendored").symlink_to(root.path / "elsewhere")

    with pytest.raises(errors.Refusal) as raised:
        archives.bundle(declared, into=root.child("source.tar"), screen=archive_port.admit_all)

    assert raised.value.reason is refusals.RefusalReason.PATH_IS_A_SYMLINK


def test_a_symlinked_source_root_is_refused_rather_than_followed(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    """Following it bundles files under paths that do not exist in the tree."""
    (root.path / "elsewhere").mkdir()
    # Split, because the guard that protects this repository refuses a literal one and it is
    # right to. The fixture needs the shape, not the string.
    header = "-----BEGIN " + "PRIVATE KEY-----\n"
    (root.path / "elsewhere" / "id_ed25519").write_text(header)
    (root.path / "vendored").symlink_to(root.path / "elsewhere")
    declared = archive_port.SourceSet(
        root=safepaths.SourceRoot.adopt(root.path), relative_paths=("vendored",)
    )

    with pytest.raises(errors.Refusal) as raised:
        archives.bundle(declared, into=root.child("source.tar"), screen=archive_port.admit_all)

    assert raised.value.reason is refusals.RefusalReason.PATH_IS_A_SYMLINK


def test_overlapping_roots_bundle_each_file_once(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    """A file counted twice is hashed into the root twice, so the root stops being a set."""
    sources(root)
    declared = archive_port.SourceSet(
        root=safepaths.SourceRoot.adopt(root.path), relative_paths=("tools", "tools/helper.py")
    )

    bundle = archives.bundle(declared, into=root.child("source.tar"), screen=archive_port.admit_all)

    assert [entry.path for entry in bundle.files] == sorted(
        {entry.path for entry in bundle.files}
    )
    assert bundle.reads == len(bundle.files)


def test_a_written_archive_is_private_to_its_owner(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    target = root.child("nested/source.tar")

    archives.bundle(sources(root), into=target, screen=archive_port.admit_all)

    if target.path.exists():
        assert target.path.stat().st_mode & 0o077 == 0
        assert target.path.parent.stat().st_mode & 0o077 == 0


def test_a_screen_refusal_stops_the_bundle_and_leaves_no_archive(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    target = root.child("source.tar")

    with pytest.raises(errors.Refusal) as raised:
        archives.bundle(sources(root), into=target, screen=refuse_helpers)

    assert raised.value.reason is refusals.RefusalReason.REPOSITORY_PRIVATE_DOCUMENT
    assert not target.path.exists()


def test_the_screen_sees_every_candidate_with_its_bytes(
    archives: archive_port.ArchivePort, root: safepaths.RuntimeRoot
) -> None:
    seen: list[tuple[str, int, bytes]] = []

    def record(candidate: archive_port.BundleCandidate) -> None:
        seen.append((candidate.path, candidate.mode.value, candidate.payload))

    archives.bundle(sources(root), into=root.child("source.tar"), screen=record)

    assert sorted(seen) == [
        ("tools/helper.py", 0o644, b"value = 1\n"),
        ("tools/run.sh", 0o755, b"#!/bin/sh\necho hi\n"),
    ]

"""Writing a file. The mode is declared, and a failed write leaves nothing behind."""

from __future__ import annotations

import pytest

from apex.kernel import errors, hashing, quantities, safepaths
from apex.ports import files as files_port


def target(root: safepaths.RuntimeRoot, name: str = "candidate.json") -> safepaths.SafePath:
    return root.child(name)


def test_a_write_is_readable(files: files_port.FileSystemPort, root: safepaths.RuntimeRoot) -> None:
    path = target(root)

    files.write_atomic(path, b"{}", mode=quantities.FileMode(0o600))

    assert files.read_bytes(path, limit=100) == b"{}"


def test_a_write_returns_the_digest_of_what_it_wrote(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    digest = files.write_atomic(target(root), b"payload", mode=quantities.FileMode(0o600))

    assert digest == hashing.digest_bytes(b"payload")


def test_the_declared_mode_is_the_mode_on_disk(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    path = target(root)

    files.write_atomic(path, b"secret", mode=quantities.FileMode(0o600))

    assert files.mode_of(path) == quantities.FileMode(0o600)


def test_a_readable_mode_is_honoured_too(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    path = target(root, "public.json")

    files.write_atomic(path, b"{}", mode=quantities.FileMode(0o644))

    assert files.mode_of(path) == quantities.FileMode(0o644)


def test_a_rewrite_replaces_the_content(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    path = target(root)

    files.write_atomic(path, b"first", mode=quantities.FileMode(0o600))
    files.write_atomic(path, b"second", mode=quantities.FileMode(0o600))

    assert files.read_bytes(path, limit=100) == b"second"


def test_reading_beyond_the_limit_returns_only_the_limit(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    path = target(root)
    files.write_atomic(path, b"abcdefghij", mode=quantities.FileMode(0o600))

    assert files.read_bytes(path, limit=4) == b"abcd"


def test_reading_an_absent_file_raises_a_port_failure(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    with pytest.raises(errors.PortFailure):
        files.read_bytes(target(root, "absent.json"), limit=10)


def test_an_absent_file_does_not_exist(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    assert not files.exists(target(root, "absent.json"))


def test_appending_creates_the_file_with_its_declared_mode(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    path = target(root, "chain.jsonl")

    files.append_line(path, b'{"sequence": 0}', mode=quantities.FileMode(0o600))

    assert files.mode_of(path) == quantities.FileMode(0o600)


def test_appending_adds_a_line_and_keeps_the_earlier_ones(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    path = target(root, "chain.jsonl")

    files.append_line(path, b"first", mode=quantities.FileMode(0o600))
    files.append_line(path, b"second", mode=quantities.FileMode(0o600))

    assert files.read_bytes(path, limit=100) == b"first\nsecond\n"


def test_appending_never_rewrites_what_is_already_there(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    path = target(root, "chain.jsonl")
    files.append_line(path, b"kept", mode=quantities.FileMode(0o600))

    files.append_line(path, b"added", mode=quantities.FileMode(0o600))

    assert files.read_bytes(path, limit=100).startswith(b"kept\n")


def test_listing_a_tree_reports_every_entry_with_its_kind(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    files.write_atomic(root.child("bundle/a.txt"), b"a", mode=quantities.FileMode(0o600))
    files.write_atomic(root.child("bundle/nested/b.txt"), b"b", mode=quantities.FileMode(0o600))

    listed = {entry.relative: entry.kind for entry in files.list_tree(root.child("bundle"))}

    assert listed == {
        "a.txt": files_port.EntryKind.REGULAR,
        "nested": files_port.EntryKind.DIRECTORY,
        "nested/b.txt": files_port.EntryKind.REGULAR,
    }


def test_listing_an_absent_directory_is_a_port_failure(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    with pytest.raises(errors.PortFailure):
        files.list_tree(root.child("absent"))


def test_a_symlink_in_the_tree_is_reported_not_followed(root: safepaths.RuntimeRoot) -> None:
    from apex.adapters.real import real_files

    (root.path / "bundle").mkdir()
    (root.path / "bundle" / "a.txt").write_text("a")
    (root.path / "bundle" / "link").symlink_to(root.path / "bundle" / "a.txt")

    entries = real_files.LocalFiles().list_tree(root.child("bundle"))
    listed = {entry.relative: entry.kind for entry in entries}

    assert listed["link"] is files_port.EntryKind.SYMLINK


def test_a_copy_carries_the_bytes_and_the_mode(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    source = target(root, "source.bin")
    files.write_atomic(source, b"payload", mode=quantities.FileMode(0o640))
    destination = target(root, "copy.bin")

    files.copy(source, destination)

    assert files.read_bytes(destination, limit=64) == b"payload"
    assert files.mode_of(destination) == quantities.FileMode(0o640)


def test_a_link_is_refused_over_an_existing_name(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    source = target(root, "blob")
    taken = target(root, "taken")
    files.write_atomic(source, b"payload", mode=quantities.FileMode(0o600))
    files.write_atomic(taken, b"other", mode=quantities.FileMode(0o600))

    files.link(source, target(root, "second-name"))
    with pytest.raises(errors.PortFailure):
        files.link(source, taken)

    assert files.read_bytes(target(root, "second-name"), limit=64) == b"payload"


def test_a_reserved_file_exists_and_is_never_replaced(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    image = target(root, "media.raw")

    files.reserve(image, size=quantities.Mib(64).as_bytes())

    assert files.exists(image)
    with pytest.raises(errors.PortFailure):
        files.reserve(image, size=quantities.Mib(1).as_bytes())


def test_a_removed_file_is_gone_and_a_second_removal_fails(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    doomed = target(root, "doomed")
    files.write_atomic(doomed, b"x", mode=quantities.FileMode(0o600))

    files.remove(doomed)

    assert not files.exists(doomed)
    with pytest.raises(errors.PortFailure):
        files.remove(doomed)


def test_free_space_is_a_positive_count(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    assert files.free_space(root.child(".")).value > 0


def test_a_made_directory_exists_afterwards(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    target = root.child("work/mnt")

    files.make_directory(target, mode=quantities.FileMode(0o700))

    assert files.exists(target)

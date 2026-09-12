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

    files.reserve(image, size=quantities.Mib(64).as_bytes(), mode=quantities.FileMode(0o600))

    assert files.exists(image)
    assert files.mode_of(image) == quantities.FileMode(0o600)
    with pytest.raises(errors.PortFailure):
        files.reserve(image, size=quantities.Mib(1).as_bytes(), mode=quantities.FileMode(0o600))


def test_a_patch_changes_bytes_in_place(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    blob = target(root, "blob")
    files.write_atomic(blob, b"0123456789", mode=quantities.FileMode(0o600))

    files.patch(blob, offset=2, payload=b"XY")

    assert files.read_bytes(blob, limit=64) == b"01XY456789"


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


def link_from(
    files: files_port.FileSystemPort, path: safepaths.SafePath, *, to: safepaths.SafePath
) -> None:
    """The one place the two adapters differ: a link is on disk, or declared to the fake."""
    from apex.adapters.fakes import fake_files

    if isinstance(files, fake_files.MemoryFiles):
        files.symlink(path, target=to)
    else:
        path.path.parent.mkdir(parents=True, exist_ok=True)
        path.path.symlink_to(to.path)


def at(root: safepaths.RuntimeRoot, name: str) -> safepaths.SafePath:
    """A path spelt below the root without resolving it, which `child` would do to a link."""
    return safepaths.SafePath(root.path / name)


def test_listing_a_directory_reports_its_direct_children_only(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    private = quantities.FileMode(0o600)
    files.write_atomic(root.child("bundle/a.txt"), b"a", mode=private)
    files.write_atomic(root.child("bundle/nested/b.txt"), b"b", mode=private)
    link_from(files, at(root, "bundle/alias"), to=root.child("bundle/a.txt"))

    listed = {entry.relative: entry.kind for entry in files.list_directory(root.child("bundle"))}

    assert listed == {
        "a.txt": files_port.EntryKind.REGULAR,
        "alias": files_port.EntryKind.SYMLINK,
        "nested": files_port.EntryKind.DIRECTORY,
    }


def test_listing_an_absent_directory_directly_is_a_port_failure(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    with pytest.raises(errors.PortFailure):
        files.list_directory(root.child("absent"))


def test_resolving_follows_every_link_to_the_file(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    files.write_atomic(root.child("devices/vda"), b"", mode=quantities.FileMode(0o600))
    link_from(files, at(root, "class/vda"), to=root.child("devices/vda"))
    link_from(files, at(root, "alias"), to=root.child("class/vda"))

    assert files.resolve(at(root, "alias")) == root.child("devices/vda")


def test_a_read_through_a_link_reaches_the_target(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    files.write_atomic(root.child("devices/vda/dev"), b"253:0\n", mode=quantities.FileMode(0o600))
    link_from(files, at(root, "class/vda"), to=root.child("devices/vda"))

    assert files.read_bytes(at(root, "class/vda/dev"), limit=16) == b"253:0\n"


def test_resolving_a_dangling_link_is_a_port_failure(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    link_from(files, at(root, "dangling"), to=root.child("absent"))

    with pytest.raises(errors.PortFailure):
        files.resolve(at(root, "dangling"))


def test_inspecting_a_file_reports_its_kind_and_mode_and_no_device(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    files.write_atomic(root.child("guard.sh"), b"#!/bin/sh\n", mode=quantities.FileMode(0o755))

    seen = files.inspect(root.child("guard.sh"))

    assert seen.kind is files_port.EntryKind.REGULAR
    assert seen.mode == quantities.FileMode(0o755)
    assert seen.device is None
    assert seen.label is None or isinstance(seen.label, str)


def test_inspecting_a_link_reports_the_link_and_never_follows_it(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    files.write_atomic(root.child("guard.sh"), b"#!/bin/sh\n", mode=quantities.FileMode(0o755))
    link_from(files, at(root, "alias"), to=root.child("guard.sh"))

    assert files.inspect(at(root, "alias")).kind is files_port.EntryKind.SYMLINK


def test_inspecting_an_absent_path_is_a_port_failure(
    files: files_port.FileSystemPort, root: safepaths.RuntimeRoot
) -> None:
    with pytest.raises(errors.PortFailure):
        files.inspect(root.child("absent"))


def test_a_device_node_reports_its_number() -> None:
    """The real adapter reads the null device every Linux host has; the fake is told one."""
    from pathlib import Path

    from apex.adapters.fakes import fake_files
    from apex.adapters.real import real_files

    null = safepaths.SafePath(Path("/dev/null"))
    fake = fake_files.MemoryFiles()
    fake.devices[str(null)] = files_port.DeviceNumber(1, 3)

    real_seen = real_files.LocalFiles().inspect(null)
    fake_seen = fake.inspect(null)

    assert real_seen.device == files_port.DeviceNumber(1, 3)
    assert real_seen.kind is files_port.EntryKind.OTHER
    assert fake_seen.device == real_seen.device
    assert fake_seen.kind is real_seen.kind


def test_a_device_number_is_parsed_from_the_sysfs_spelling() -> None:
    number = files_port.DeviceNumber.parse("253:16\n")

    assert (number.major, number.minor) == (253, 16)
    assert number.rendered == "253:16"


def test_a_device_number_that_is_not_two_integers_is_refused() -> None:
    with pytest.raises(errors.Refusal):
        files_port.DeviceNumber.parse("vda")

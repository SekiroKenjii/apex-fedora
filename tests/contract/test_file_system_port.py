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

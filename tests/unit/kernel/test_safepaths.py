"""A path that exists as a value is a path that was checked.

The current code validates with `regular_file()` and then discards the result at 86 call
sites, interpolating the unchecked original into an argument list. That is a type error here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.kernel import errors, refusals, safepaths


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)


def test_a_regular_file_inside_the_root_is_accepted(root: safepaths.RuntimeRoot) -> None:
    target = root.path / "candidate.json"
    target.write_text("{}")

    assert safepaths.SafePath.regular_file(target, within=root).path == target


def test_a_path_outside_the_root_is_refused(root: safepaths.RuntimeRoot, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere.json"
    outside.write_text("{}")

    with pytest.raises(errors.Refusal) as raised:
        safepaths.SafePath.regular_file(outside, within=root)

    assert raised.value.reason is refusals.RefusalReason.PATH_OUTSIDE_RUNTIME_ROOT


def test_a_symlink_is_refused_even_when_it_points_inside(root: safepaths.RuntimeRoot) -> None:
    real = root.path / "real.json"
    real.write_text("{}")
    link = root.path / "link.json"
    link.symlink_to(real)

    with pytest.raises(errors.Refusal) as raised:
        safepaths.SafePath.regular_file(link, within=root)

    assert raised.value.reason is refusals.RefusalReason.PATH_IS_A_SYMLINK


def test_a_directory_is_not_a_regular_file(root: safepaths.RuntimeRoot) -> None:
    with pytest.raises(errors.Refusal) as raised:
        safepaths.SafePath.regular_file(root.path, within=root)

    assert raised.value.reason is refusals.RefusalReason.PATH_NOT_A_REGULAR_FILE


def test_a_source_root_accepts_any_readable_directory(root: safepaths.RuntimeRoot) -> None:
    shared = root.path / "checkout"
    shared.mkdir(mode=0o755)

    assert safepaths.SourceRoot.adopt(shared).path == shared.resolve()


def test_a_source_root_refuses_a_symlink_and_a_file(root: safepaths.RuntimeRoot) -> None:
    plain = root.path / "plain.json"
    plain.write_bytes(b"{}")
    link = root.path / "link"
    link.symlink_to(root.path)

    with pytest.raises(errors.Refusal) as from_file:
        safepaths.SourceRoot.adopt(plain)
    with pytest.raises(errors.Refusal) as from_link:
        safepaths.SourceRoot.adopt(link)

    assert from_file.value.reason is refusals.RefusalReason.PATH_NOT_A_DIRECTORY
    assert from_link.value.reason is refusals.RefusalReason.PATH_IS_A_SYMLINK


def test_a_file_offered_as_a_runtime_root_is_refused_as_not_a_directory(
    root: safepaths.RuntimeRoot,
) -> None:
    plain = root.path / "plain.json"
    plain.write_bytes(b"{}")

    with pytest.raises(errors.Refusal) as resolved:
        safepaths.RuntimeRoot.resolve(plain, permitted=[root.path])
    with pytest.raises(errors.Refusal) as adopted:
        safepaths.RuntimeRoot.adopt(plain)

    assert resolved.value.reason is refusals.RefusalReason.PATH_NOT_A_DIRECTORY
    assert adopted.value.reason is refusals.RefusalReason.PATH_NOT_A_DIRECTORY


def test_a_traversal_escape_is_refused(root: safepaths.RuntimeRoot) -> None:
    with pytest.raises(errors.Refusal):
        safepaths.SafePath.regular_file(root.path / ".." / "escape", within=root)


def test_a_path_holding_an_option_separator_is_refused(root: safepaths.RuntimeRoot) -> None:
    """A comma in a path silently splits a QEMU device argument."""
    target = root.path / "disk,if=none.qcow2"
    target.write_text("")

    with pytest.raises(errors.Refusal) as raised:
        safepaths.SafePath.regular_file(target, within=root)

    assert raised.value.reason is refusals.RefusalReason.PATH_CONTAINS_OPTION_SEPARATOR


def test_the_root_refuses_a_location_outside_the_permitted_bases(tmp_path: Path) -> None:
    with pytest.raises(errors.Refusal) as raised:
        safepaths.RuntimeRoot.resolve(Path("/etc"), permitted=(tmp_path,))

    assert raised.value.reason is refusals.RefusalReason.RUNTIME_ROOT_NOT_PERMITTED


def test_the_root_refuses_a_directory_that_is_not_private(tmp_path: Path) -> None:
    base = tmp_path / "loose"
    base.mkdir(mode=0o755)

    with pytest.raises(errors.Refusal) as raised:
        safepaths.RuntimeRoot.resolve(base, permitted=(tmp_path,))

    assert raised.value.reason is refusals.RefusalReason.RUNTIME_ROOT_NOT_PRIVATE


def test_the_root_accepts_a_private_directory_below_a_permitted_base(tmp_path: Path) -> None:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)

    assert safepaths.RuntimeRoot.resolve(base, permitted=(tmp_path,)).path == base


def test_the_root_derives_contained_paths(root: safepaths.RuntimeRoot) -> None:
    assert root.child("evidence/boot.json").path == root.path / "evidence" / "boot.json"


def test_the_root_refuses_to_derive_a_path_that_escapes(root: safepaths.RuntimeRoot) -> None:
    with pytest.raises(errors.Refusal):
        root.child("../outside")


def test_a_remote_path_is_absolute_and_free_of_shell_metacharacters() -> None:
    assert str(safepaths.RemotePath("/var/tmp/apex-run")) == "/var/tmp/apex-run"


@pytest.mark.parametrize("value", ["relative/path", "/var/tmp/$(whoami)", "/var/tmp/a;b", "/a b"])
def test_a_dangerous_remote_path_is_refused(value: str) -> None:
    with pytest.raises(errors.Refusal):
        safepaths.RemotePath(value)

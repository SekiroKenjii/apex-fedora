"""Adopting a directory is still a check, not a bypass.

`adopt` exists so a test and the composition root can hand in a directory they already made.
Accepting any path at all would make every containment rule in the system optional.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.kernel import errors, refusals, safepaths


def test_a_private_directory_is_adopted(tmp_path: Path) -> None:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)

    assert safepaths.RuntimeRoot.adopt(base).path == base


def test_a_group_readable_directory_is_refused(tmp_path: Path) -> None:
    base = tmp_path / "loose"
    base.mkdir(mode=0o755)

    with pytest.raises(errors.Refusal) as raised:
        safepaths.RuntimeRoot.adopt(base)

    assert raised.value.reason is refusals.RefusalReason.RUNTIME_ROOT_NOT_PRIVATE


def test_a_file_is_not_a_root(tmp_path: Path) -> None:
    target = tmp_path / "not-a-directory"
    target.write_text("")

    with pytest.raises(errors.Refusal):
        safepaths.RuntimeRoot.adopt(target)


def test_an_absent_directory_is_refused(tmp_path: Path) -> None:
    with pytest.raises(errors.Refusal):
        safepaths.RuntimeRoot.adopt(tmp_path / "absent")


def test_a_symlinked_directory_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)

    with pytest.raises(errors.Refusal) as raised:
        safepaths.RuntimeRoot.adopt(link)

    assert raised.value.reason is refusals.RefusalReason.PATH_IS_A_SYMLINK

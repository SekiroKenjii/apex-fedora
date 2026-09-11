"""A private runtime root for the trust tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.kernel import safepaths


@pytest.fixture
def root(tmp_path: Path) -> safepaths.RuntimeRoot:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    return safepaths.RuntimeRoot.adopt(base)

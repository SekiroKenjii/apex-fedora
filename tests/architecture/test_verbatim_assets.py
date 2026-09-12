"""A verbatim asset is the older tree's file, byte for byte, for as long as that tree exists.

The point of carrying a safety artifact unrewritten is lost the moment the two copies drift.
This holds every asset equal to the file it names under `guest/`, and holds the typed
wrapper's digest to the same bytes, so an edit to either side fails here first.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from apex.agent import desktopprograms, fingerprintharness
from apex.trust import preflight

REPOSITORY = Path(__file__).resolve().parents[2]
ASSETS = REPOSITORY / "src" / "apex" / "assets" / "verbatim"
SUFFIX = ".verbatim"


def assets() -> list[Path]:
    return sorted(ASSETS.glob(f"*{SUFFIX}"))


def older_copy(asset: Path) -> Path:
    return REPOSITORY / "guest" / asset.name.removesuffix(SUFFIX)


def test_the_asset_package_holds_at_least_one_verbatim_file() -> None:
    assert assets()


def test_every_verbatim_asset_equals_the_older_tree_s_file_of_the_same_name() -> None:
    differing = [
        asset.name
        for asset in assets()
        if asset.read_bytes() != older_copy(asset).read_bytes()
    ]

    assert differing == []


def test_the_preflight_wrapper_carries_the_older_file_s_digest() -> None:
    expected = hashlib.sha256((REPOSITORY / "guest" / preflight.ASSET).read_bytes()).hexdigest()

    assert preflight.digest().hex == expected


def test_the_fingerprint_harness_wrapper_carries_the_older_file_s_digest() -> None:
    older = REPOSITORY / "guest" / fingerprintharness.ASSET

    assert fingerprintharness.digest().hex == hashlib.sha256(older.read_bytes()).hexdigest()


@pytest.mark.parametrize("program", [desktopprograms.RENDER, desktopprograms.THEME])
def test_each_desktop_program_wrapper_carries_the_older_file_s_digest(
    program: desktopprograms.Program,
) -> None:
    older = REPOSITORY / "guest" / program.asset

    assert program.digest().hex == hashlib.sha256(older.read_bytes()).hexdigest()

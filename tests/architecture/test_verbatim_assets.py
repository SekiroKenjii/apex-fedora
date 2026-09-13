"""A verbatim asset is the older tree's file, byte for byte, for as long as that file exists.

The point of carrying a safety artifact unrewritten is lost the moment the two copies drift.
This holds every asset equal to the file it names under `guest/` while that file is still
shipped, and holds each typed wrapper's digest to the asset's bytes, so an edit to either
side fails here first.
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
        if older_copy(asset).is_file() and asset.read_bytes() != older_copy(asset).read_bytes()
    ]

    assert differing == []


def asset_digest(name: str) -> str:
    return hashlib.sha256((ASSETS / f"{name}{SUFFIX}").read_bytes()).hexdigest()


def test_the_preflight_wrapper_carries_the_asset_s_digest() -> None:
    assert preflight.digest().hex == asset_digest(preflight.ASSET)


def test_the_fingerprint_harness_wrapper_carries_the_asset_s_digest() -> None:
    assert fingerprintharness.digest().hex == asset_digest(fingerprintharness.ASSET)


@pytest.mark.parametrize("program", [desktopprograms.RENDER, desktopprograms.THEME])
def test_each_desktop_program_wrapper_carries_the_asset_s_digest(
    program: desktopprograms.Program,
) -> None:
    assert program.digest().hex == asset_digest(program.asset)

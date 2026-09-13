"""Releases register by being there, and exactly one of them is the current one."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.kernel import errors, identifiers
from apex.model import release
from apex.registry import decorators, registry
from apex.targeting import releases
from apex.targeting.releases import cachyos_release, fedora44_release

SOURCE = Path(__file__).resolve().parents[3] / "src" / "apex" / "targeting" / "releases"


def test_every_release_module_declares_one_profile_and_the_registry_holds_them_all() -> None:
    modules = sorted(p.stem for p in SOURCE.glob("*.py") if not p.name.startswith("_"))

    assert len(releases.registered()) == len(modules)
    assert [str(profile.id) for profile in releases.registered()] == ["cachyos", "fedora-44"]


def test_the_current_release_is_the_one_supported_profile() -> None:
    assert releases.current() is fedora44_release.PROFILE
    assert not cachyos_release.PROFILE.supported
    assert releases.lookup(identifiers.ProfileId("fedora-44")) is fedora44_release.PROFILE
    assert releases.lookup(identifiers.ProfileId("fedora-45")) is None


def test_two_supported_releases_are_a_registration_fault(monkeypatch: pytest.MonkeyPatch) -> None:
    held: registry.Registry[str, release.ReleaseProfile] = registry.Registry("release")
    for name in ("fedora-44", "fedora-45"):
        held.add(name, fedora44_release.PROFILE, at=decorators.caller(1))
    monkeypatch.setattr(releases, "_collector", held)
    monkeypatch.setattr(releases, "_sealed", None)

    with pytest.raises(errors.RegistrationError):
        releases.sealed()

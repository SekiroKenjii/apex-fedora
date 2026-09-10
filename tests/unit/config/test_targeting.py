"""A release is a file. The next one is another file."""

from __future__ import annotations

import dataclasses

from apex.kernel import refusals
from apex.model import release
from apex.targeting.releases import cachyos_release, fedora44_release


def test_the_current_release_matches_the_recorded_project_file() -> None:
    profile = fedora44_release.PROFILE

    assert profile.major == 44
    assert str(profile.dist_tag.value) == "fc44"
    assert profile.mock_root == "fedora-44-x86_64"
    assert profile.supported


def test_the_release_renders_the_greenboot_package_the_image_installs() -> None:
    coordinate = fedora44_release.PROFILE.render_nevra(
        name="greenboot", version="0.16.4", build="0", architecture="x86_64"
    )

    assert coordinate.filename == "greenboot-0.16.4-0.fc44.x86_64.rpm"


def test_the_release_renders_a_patched_package_suffix() -> None:
    coordinate = fedora44_release.PROFILE.render_nevra(
        name="libfprint",
        version="1.94.100",
        build="1",
        architecture="x86_64",
        vendor_suffix="apex1",
    )

    assert coordinate.filename == "libfprint-1.94.100-1.fc44.apex1.x86_64.rpm"


def test_the_desktop_profile_matches_the_image() -> None:
    assert fedora44_release.DESKTOP.major == 50
    assert fedora44_release.DESKTOP.control_centre_version == "50.4"


def test_the_comparison_lineage_is_declared_and_refused() -> None:
    assert not cachyos_release.PROFILE.supported
    assert cachyos_release.PROFILE.refusal is refusals.RefusalReason.PROFILE_NOT_REVIEWED


def test_no_release_profile_can_hold_a_digest() -> None:
    for field in dataclasses.fields(release.ReleaseProfile):
        assert "Digest" not in str(field.type)


def test_a_profile_module_declares_exactly_one_profile() -> None:
    for module in (fedora44_release, cachyos_release):
        assert hasattr(module, "PROFILE")

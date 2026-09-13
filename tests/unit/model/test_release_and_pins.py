"""A chosen shape and a reviewed hash are different kinds of thing.

Storing both in one object is why upgrading Fedora today means editing eleven files, and
why a kernel erratum means hand-editing a file labelled lock.
"""

from __future__ import annotations

import dataclasses

import pytest

from apex.kernel import errors, identifiers, refusals
from apex.model import pins, release

FEDORA_44 = release.ReleaseProfile(
    id=identifiers.ProfileId("fedora-44"),
    major=44,
    os_id="fedora",
    os_release_version_id="44",
    dist_tag=release.DistTag("fc44"),
    mock_root="fedora-44-x86_64",
    efi_vendor_directory="fedora",
    architecture="x86_64",
    supported=True,
)

ARCHIVE = pins.ArchiveCoordinate(
    project="libfprint", version="1.94.100", filename="libfprint-1.94.100.tar.xz"
)
DIGEST = identifiers.Digest("a" * 64)


def test_a_release_profile_carries_no_digest_field() -> None:
    """A profile edit must never be able to weaken a pin."""
    annotations = {
        field.name: field.type for field in dataclasses.fields(release.ReleaseProfile)
    }

    for name, annotation in annotations.items():
        assert "Digest" not in str(annotation), f"{name} would let a profile hold a hash"


def test_a_pinned_artifact_carries_no_release_field() -> None:
    """Changing the target release must not be able to change a hash."""
    annotations = {field.name: field.type for field in dataclasses.fields(pins.PinnedArtifact)}

    for name, annotation in annotations.items():
        assert "Release" not in str(annotation), f"{name} would couple a pin to a release"


def test_a_release_renders_the_package_release_suffix() -> None:
    assert FEDORA_44.dist_tag.applied("1") == "1.fc44"


def test_a_release_renders_a_patched_package_suffix() -> None:
    assert FEDORA_44.dist_tag.applied("1", vendor_suffix="apex1") == "1.fc44.apex1"


def test_a_release_renders_a_package_coordinate() -> None:
    coordinate = FEDORA_44.render_nevra(
        name="greenboot", version="0.16.4", build="0", architecture="x86_64"
    )

    assert coordinate.filename == "greenboot-0.16.4-0.fc44.x86_64.rpm"


def test_the_next_release_is_a_new_profile_and_nothing_else() -> None:
    fedora_45 = dataclasses.replace(
        FEDORA_44,
        id=identifiers.ProfileId("fedora-45"),
        major=45,
        os_release_version_id="45",
        dist_tag=release.DistTag("fc45"),
        mock_root="fedora-45-x86_64",
    )

    assert fedora_45.render_nevra(
        name="greenboot", version="0.16.4", build="0", architecture="x86_64"
    ).filename == "greenboot-0.16.4-0.fc45.x86_64.rpm"


def test_an_unreviewed_profile_declares_why_it_is_refused() -> None:
    cachyos = dataclasses.replace(
        FEDORA_44,
        id=identifiers.ProfileId("cachyos"),
        supported=False,
        refusal=refusals.RefusalReason.PROFILE_NOT_REVIEWED,
    )

    assert not cachyos.supported
    assert cachyos.refusal is refusals.RefusalReason.PROFILE_NOT_REVIEWED


def test_a_supported_profile_may_not_also_declare_a_refusal() -> None:
    with pytest.raises(errors.RegistrationError):
        dataclasses.replace(FEDORA_44, refusal=refusals.RefusalReason.PROFILE_NOT_REVIEWED)


def test_a_pin_renders_its_url_from_the_profile_not_from_itself() -> None:
    pin = pins.PinnedArtifact(
        coordinate=ARCHIVE,
        sha256=DIGEST,
        verification=pins.VerificationLevel.CHECKSUM,
        reviewed=pins.ReviewRecord(reviewer="thuongvo", date="2026-09-09"),
    )

    url = pin.url(base="https://kojipkgs.fedoraproject.org/packages")

    assert url.endswith("libfprint-1.94.100.tar.xz")
    assert "fc44" not in url


def test_a_verification_level_propagates_into_what_may_be_claimed() -> None:
    weak = pins.PinnedArtifact(
        coordinate=ARCHIVE,
        sha256=DIGEST,
        verification=pins.VerificationLevel.TLS_ONLY,
        reviewed=pins.ReviewRecord(reviewer="thuongvo", date="2026-09-09"),
    )

    assert not weak.verification.is_cryptographically_bound
    assert pins.VerificationLevel.SIGNED.is_cryptographically_bound
    assert pins.VerificationLevel.CHECKSUM.is_cryptographically_bound


def test_a_version_constraint_can_defer_to_the_image() -> None:
    constraint = release.SameAsImage()

    assert constraint.satisfied_by("7.1.13-200.fc44.x86_64", observed="7.1.13-200.fc44.x86_64")
    assert not constraint.satisfied_by("7.1.13-200.fc44.x86_64", observed="7.1.14-200.fc44.x86_64")


def test_an_exact_constraint_pins_a_literal() -> None:
    assert release.Exactly("1.94.100").satisfied_by("1.94.100", observed="1.94.100")


def test_an_at_least_constraint_accepts_a_newer_version() -> None:
    assert release.AtLeast("6.19").satisfied_by("6.19", observed="7.1")
    assert not release.AtLeast("6.19").satisfied_by("6.19", observed="6.18")


def test_upstream_prose_is_corroboration_and_says_which_release_it_was_checked_against() -> None:
    signal = release.UpstreamSignal(
        structural="greenboot-healthcheck.service",
        prose="Boot Status is GREEN - Health Check SUCCESS",
        validated_against=FEDORA_44.id,
    )

    assert signal.structural
    assert str(signal.validated_against) == "fedora-44"

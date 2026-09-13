"""Identity is a type, so a malformed value cannot travel."""

from __future__ import annotations

import pytest

from apex.kernel import errors, identifiers, refusals

FULL_DIGEST = "sha256:2daf0bc614838352a65af743e2e0efb658e040169dd95e25520eb1334f42c912"
BARE_DIGEST = FULL_DIGEST.removeprefix("sha256:")
BUILD_ID = "ee97157d34b9480186730786268f6a0c"


def test_a_digest_parses_the_prefixed_form() -> None:
    assert identifiers.Digest.parse(FULL_DIGEST).hex == BARE_DIGEST


def test_a_digest_parses_the_bare_form() -> None:
    assert identifiers.Digest.parse(BARE_DIGEST).hex == BARE_DIGEST


def test_a_digest_renders_the_prefixed_form() -> None:
    assert str(identifiers.Digest.parse(BARE_DIGEST)) == FULL_DIGEST


@pytest.mark.parametrize(
    "value",
    [
        "",
        "sha256:",
        BARE_DIGEST[:-1],
        BARE_DIGEST + "a",
        BARE_DIGEST.upper(),
        "sha512:" + BARE_DIGEST,
    ],
)
def test_a_malformed_digest_is_refused(value: str) -> None:
    with pytest.raises(errors.Refusal) as raised:
        identifiers.Digest.parse(value)

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_DIGEST


def test_a_build_identifier_accepts_the_thirty_two_character_form() -> None:
    assert str(identifiers.BuildId.parse(BUILD_ID)) == BUILD_ID


@pytest.mark.parametrize("value", ["", BUILD_ID[:-1], BUILD_ID + "0", BUILD_ID.upper(), "../etc"])
def test_a_malformed_build_identifier_is_refused(value: str) -> None:
    with pytest.raises(errors.Refusal) as raised:
        identifiers.BuildId.parse(value)

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_IDENTIFIER


def test_identifiers_of_different_kinds_never_compare_equal() -> None:
    assert identifiers.BuildId.parse(BUILD_ID) != identifiers.RunId.parse(BUILD_ID)


def test_an_identifier_is_hashable_and_usable_as_a_mapping_key() -> None:
    key = identifiers.CheckId("boot.ten-cycles")

    assert {key: 1}[identifiers.CheckId("boot.ten-cycles")] == 1


def test_a_check_identifier_refuses_a_name_that_is_not_dotted_lowercase() -> None:
    with pytest.raises(errors.Refusal):
        identifiers.CheckId("Boot Ten Cycles")


def test_a_package_coordinate_renders_its_own_file_name() -> None:
    package = identifiers.Nevra(
        name="libfprint", epoch=0, version="1.94.100", release="1.fc44.apex1", architecture="x86_64"
    )

    assert package.filename == "libfprint-1.94.100-1.fc44.apex1.x86_64.rpm"


def test_a_package_coordinate_parses_the_query_form_the_tools_emit() -> None:
    package = identifiers.Nevra.parse("libfprint|0:1.94.100-1.fc44.apex1.x86_64")

    assert package.name == "libfprint"
    assert package.version == "1.94.100"
    assert package.release == "1.fc44.apex1"
    assert package.architecture == "x86_64"


def test_an_image_identifier_is_a_digest() -> None:
    assert isinstance(identifiers.ImageId.parse(FULL_DIGEST), identifiers.Digest)

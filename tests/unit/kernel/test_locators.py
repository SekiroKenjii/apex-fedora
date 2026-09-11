"""A download address is https by type, and a filename is a plain basename by type."""

from __future__ import annotations

import pytest

from apex.kernel import errors, locators, refusals


def test_an_https_address_is_accepted() -> None:
    assert str(locators.HttpsUrl("https://example.invalid/a.tar.gz")).startswith("https://")


@pytest.mark.parametrize(
    "value", ["http://example.invalid/a", "ftp://x/y", "https://", "", "example"]
)
def test_anything_but_https_is_refused(value: str) -> None:
    with pytest.raises(errors.Refusal) as raised:
        locators.HttpsUrl(value)

    assert raised.value.reason is refusals.RefusalReason.URL_NOT_HTTPS


@pytest.mark.parametrize("value", ["a.tar.gz", "MapleMono-NF.zip", "x_1-2.bin"])
def test_a_plain_basename_is_accepted(value: str) -> None:
    assert str(locators.Basename(value)) == value


@pytest.mark.parametrize("value", ["../outside.tar.gz", "a/b", ".", "..", "", "a b", "a\tb"])
def test_a_name_that_is_not_a_plain_basename_is_refused(value: str) -> None:
    with pytest.raises(errors.Refusal) as raised:
        locators.Basename(value)

    assert raised.value.reason is refusals.RefusalReason.FILENAME_NOT_PLAIN

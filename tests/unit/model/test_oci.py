"""The frozen image document and the OCI manifest it must agree with."""

from __future__ import annotations

import json

import pytest

from apex.kernel import errors, refusals
from apex.model import oci

DIGEST = "sha256:" + "a" * 64
IMAGE_ID = "sha256:" + "c" * 64


def test_a_frozen_image_parses() -> None:
    image = oci.FrozenImage.parse(
        json.dumps({"profile": "fedora", "digest": DIGEST, "image_id": IMAGE_ID}).encode()
    )

    assert image.profile == "fedora"
    assert image.digest.hex == "a" * 64
    assert image.image_id.hex == "c" * 64


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b"nope",
        json.dumps({"profile": "fedora", "digest": "a" * 64, "image_id": IMAGE_ID}).encode(),
        json.dumps({"profile": "fedora", "digest": DIGEST, "image_id": "c" * 64}).encode(),
        json.dumps({"profile": "", "digest": DIGEST, "image_id": IMAGE_ID}).encode(),
        json.dumps({"profile": 3, "digest": DIGEST, "image_id": IMAGE_ID}).encode(),
    ],
)
def test_a_malformed_image_document_is_refused(payload: bytes) -> None:
    with pytest.raises(errors.Refusal) as raised:
        oci.FrozenImage.parse(payload)

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_IMAGE_DOCUMENT


def test_the_configuration_digest_is_read_from_the_oci_manifest() -> None:
    payload = json.dumps({"schemaVersion": 2, "config": {"digest": IMAGE_ID}}).encode()

    assert oci.config_digest(payload).hex == "c" * 64


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b"[]",
        b"x",
        json.dumps({"config": {}}).encode(),
        json.dumps({"config": {"digest": "zz"}}).encode(),
    ],
)
def test_an_oci_manifest_without_a_configuration_digest_is_refused(payload: bytes) -> None:
    with pytest.raises(errors.Refusal) as raised:
        oci.config_digest(payload)

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_OCI_MANIFEST

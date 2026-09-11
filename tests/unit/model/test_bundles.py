"""The signed inventory of an artifact directory, parsed once and refused when malformed."""

from __future__ import annotations

import json

import pytest

from apex.kernel import errors, refusals
from apex.model import bundles

DIGEST = "sha256:" + "a" * 64
FILE_DIGEST = "b" * 64


def document(**overrides: object) -> bytes:
    body: dict[str, object] = {"schema": 1, "digest": DIGEST, "files": {"payload.txt": FILE_DIGEST}}
    body.update(overrides)
    return json.dumps(body).encode()


def test_a_well_formed_manifest_parses() -> None:
    manifest = bundles.ArtifactManifest.parse(document(purpose="installer"))

    assert manifest.digest.hex == "a" * 64
    assert manifest.files["payload.txt"].hex == FILE_DIGEST
    assert manifest.purpose == "installer"


def test_the_permitted_paths_are_the_files_plus_the_bundle_headers() -> None:
    manifest = bundles.ArtifactManifest.parse(document())

    assert manifest.permitted_paths() == frozenset(
        {"payload.txt", bundles.MANIFEST_NAME, bundles.SIGNATURE_NAME, bundles.BUNDLED_KEY_NAME}
    )


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b"[]",
        document(schema=2),
        document(schema=True),
        document(digest="a" * 64),
        document(digest="sha256:zz"),
        document(files={}),
        document(files={"payload.txt": "short"}),
        document(files={"/etc/passwd": FILE_DIGEST}),
        document(files={"../up.txt": FILE_DIGEST}),
        document(files="payload.txt"),
    ],
)
def test_a_malformed_manifest_is_refused(payload: bytes) -> None:
    with pytest.raises(errors.Refusal) as raised:
        bundles.ArtifactManifest.parse(payload)

    assert raised.value.reason is refusals.RefusalReason.MALFORMED_ARTIFACT_MANIFEST


def test_the_oci_manifest_names_are_the_ones_the_inventory_carries() -> None:
    manifest = bundles.ArtifactManifest.parse(
        document(files={"payload-manifest.json": FILE_DIGEST, "x.qcow2": FILE_DIGEST})
    )

    assert manifest.oci_manifest_names() == ("payload-manifest.json",)

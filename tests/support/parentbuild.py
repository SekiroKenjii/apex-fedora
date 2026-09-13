"""A completed image build's three documents, agreeing with one another, where a run reads them."""

from __future__ import annotations

import json

from apex.composition import exports
from apex.kernel import hashing, identifiers, quantities, safepaths
from apex.ports import files

PARENT = identifiers.BuildId("d" * 32)
IMAGE_ID = "b" * 64
PRIVATE = quantities.FileMode(0o600)


def documents(
    filesystem: files.FileSystemPort,
    root: safepaths.RuntimeRoot,
    parent: identifiers.BuildId = PARENT,
    *,
    status: str = "PASS",
) -> identifiers.Digest:
    """Write the record, the image document and the manifest; the image's digest comes back."""
    manifest = json.dumps({"config": {"digest": f"sha256:{IMAGE_ID}"}}).encode()
    digest = hashing.digest_bytes(manifest)
    image = json.dumps({
        "profile": "fedora", "digest": str(digest), "image_id": f"sha256:{IMAGE_ID}",
    }).encode()
    record = json.dumps({
        "status": status, "kind": "image", "profile": "fedora", "source_sha256": "a" * 64,
        "remote": f"/var/tmp/apex-{parent}", "parent_build": None, "test_access": False,
    }).encode()
    filesystem.write_atomic(exports.inside(root, parent, "result.json"), record, mode=PRIVATE)
    filesystem.write_atomic(
        exports.inside(root, parent, "output/image.json"), image, mode=PRIVATE
    )
    filesystem.write_atomic(
        exports.inside(root, parent, "output/manifest.json"), manifest, mode=PRIVATE
    )
    return digest

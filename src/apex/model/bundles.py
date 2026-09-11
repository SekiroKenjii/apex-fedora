"""The signed inventory of an artifact directory.

A bundle is a directory holding the inventory, the signature over it, and the files the
inventory names. Nothing else may be present, so a file that was not signed cannot sit
beside the ones that were and be mistaken for one of them.
"""

from __future__ import annotations

import dataclasses
import json
import posixpath
import re
from collections.abc import Mapping
from typing import Self

from apex.kernel import errors, identifiers, refusals

MANIFEST_NAME = "artifacts.json"
SIGNATURE_NAME = "artifacts.sig"
BUNDLED_KEY_NAME = "development-signing.pub"
IMAGE_DOCUMENT_NAME = "image.json"
OCI_MANIFEST_NAMES = ("manifest.json", "payload-manifest.json")
SCHEMA = 1
PREFIXED_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
HEX_DIGEST = re.compile(r"[0-9a-f]{64}")
UPWARD = ".."


def _refuse(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.MALFORMED_ARTIFACT_MANIFEST, subject=detail)


def _relative_path(name: object) -> str:
    if not isinstance(name, str) or not name or posixpath.isabs(name):
        raise _refuse(f"file name {name!r}")
    if UPWARD in name.split("/"):
        raise _refuse(f"file name {name!r} climbs out of the bundle")
    return name


def _files(document: Mapping[str, object]) -> dict[str, identifiers.Digest]:
    listed = document.get("files")
    if not isinstance(listed, dict) or not listed:
        raise _refuse("files must be a non-empty mapping")
    files: dict[str, identifiers.Digest] = {}
    for name, digest in listed.items():
        if not isinstance(digest, str) or not HEX_DIGEST.fullmatch(digest):
            raise _refuse(f"digest of {name!r}")
        files[_relative_path(name)] = identifiers.Digest(digest)
    return files


@dataclasses.dataclass(frozen=True, slots=True)
class ArtifactManifest:
    digest: identifiers.Digest
    files: Mapping[str, identifiers.Digest]
    purpose: str | None

    @classmethod
    def parse(cls, payload: bytes) -> Self:
        try:
            document = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as fault:
            raise _refuse("not a JSON document") from fault
        if not isinstance(document, dict):
            raise _refuse("not an object")
        schema = document.get("schema")
        if isinstance(schema, bool) or schema != SCHEMA:
            raise _refuse(f"schema {schema!r}")
        digest = document.get("digest")
        if not isinstance(digest, str) or not PREFIXED_DIGEST.fullmatch(digest):
            raise _refuse(f"digest {digest!r}")
        purpose = document.get("purpose")
        return cls(
            digest=identifiers.Digest.parse(digest),
            files=_files(document),
            purpose=purpose if isinstance(purpose, str) else None,
        )

    def permitted_paths(self) -> frozenset[str]:
        return frozenset(self.files) | {MANIFEST_NAME, SIGNATURE_NAME, BUNDLED_KEY_NAME}

    def oci_manifest_names(self) -> tuple[str, ...]:
        return tuple(name for name in OCI_MANIFEST_NAMES if name in self.files)

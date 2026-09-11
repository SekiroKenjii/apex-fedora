"""The frozen image document, and the OCI manifest it has to agree with.

`image.json` names the profile, the manifest digest and the configuration digest of the image
a build produced. Both digests are read back off the packaged OCI manifest at verification, so
the document cannot name an image other than the one that was packaged.
"""

from __future__ import annotations

import dataclasses
import json
import re
from typing import Self

from apex.kernel import errors, identifiers, refusals

PREFIXED_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
CONFIG_KEY = "config"
DIGEST_KEY = "digest"


def _document(payload: bytes, reason: refusals.RefusalReason) -> dict[str, object]:
    try:
        document = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as fault:
        raise errors.Refusal(reason, subject="not a JSON document") from fault
    if not isinstance(document, dict):
        raise errors.Refusal(reason, subject="not an object")
    return document


def _prefixed(value: object, *, field: str, reason: refusals.RefusalReason) -> str:
    if not isinstance(value, str) or not PREFIXED_DIGEST.fullmatch(value):
        raise errors.Refusal(reason, subject=f"{field} {value!r}")
    return value


@dataclasses.dataclass(frozen=True, slots=True)
class FrozenImage:
    profile: str
    digest: identifiers.Digest
    image_id: identifiers.ImageId

    @classmethod
    def parse(cls, payload: bytes) -> Self:
        reason = refusals.RefusalReason.MALFORMED_IMAGE_DOCUMENT
        document = _document(payload, reason)
        profile = document.get("profile")
        if not isinstance(profile, str) or not profile:
            raise errors.Refusal(reason, subject=f"profile {profile!r}")
        return cls(
            profile=profile,
            digest=identifiers.Digest.parse(
                _prefixed(document.get("digest"), field="digest", reason=reason)
            ),
            image_id=identifiers.ImageId.parse(
                _prefixed(document.get("image_id"), field="image_id", reason=reason)
            ),
        )


def config_digest(manifest_payload: bytes) -> identifiers.ImageId:
    reason = refusals.RefusalReason.MALFORMED_OCI_MANIFEST
    document = _document(manifest_payload, reason)
    config = document.get(CONFIG_KEY)
    if not isinstance(config, dict):
        raise errors.Refusal(reason, subject="no configuration descriptor")
    return identifiers.ImageId.parse(
        _prefixed(config.get(DIGEST_KEY), field="config.digest", reason=reason)
    )

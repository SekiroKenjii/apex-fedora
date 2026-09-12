"""Two signed images over the frozen payload, one a child of the other, for recovery tests.

The signing policy, the container recipes and the report shape are decided here. Building,
signing and packaging run in the isolated builder.
"""

from __future__ import annotations

import base64
import dataclasses
import re
from collections.abc import Mapping

from apex.kernel import encoding, errors, identifiers, quantities, refusals

REQUIRED_FREE = quantities.Gib(24)
VERSIONS = ("a", "b")
CASES = (("a", "a"), ("b", "b"), ("wrong-key", "b"), ("unsigned", "b"))
FIXTURE_ROOT = "/var/lib/apex-update-fixture"
IMAGE_PREFIX = "localhost/apex-recovery-"
PAYLOAD_PREFIX = "localhost/apex-payload:"
SCOPE = "signed offline update fixture, not a release candidate"
RPM_QUERY = ("rpm", "-qa", "--qf", "%{NAME}-%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n")
LINT = ("bootc", "container", "lint", "--fatal-warnings")
FRAGMENT = "/usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg"
RECOVERY_CHECK = (
    "sh", "-c",
    "set -eu; sha256sum /etc/greenboot/greenboot.conf /usr/share/apex/greenboot.conf "
    f"{FRAGMENT}; "
    f'test "$(tail -c1 {FRAGMENT} | od -An -tu1 | tr -d " ")" = 10',
)
RETRY_PRESET = "system_files/usr/share/apex/greenboot.conf"
RETRY_LINE = "GREENBOOT_MAX_BOOT_ATTEMPTS=1\n"
GRUB_REPAIR = "guest/fix-grub-fragment.py"
BUILDER_POLICY = "/etc/containers/policy.json"
STORAGE_SCOPE = "[overlay@/var/lib/containers/storage]"
CASES_FROM_B = ("unsigned", "untrusted")
BLOB_NAME = re.compile(r"[a-f0-9]{64}")
SIGNATURE_PREFIX = "signature-"


def signing_policy(tag: str) -> encoding.Document:
    """Accept only the image just built from the local store, for the copy that signs it."""
    return {
        "default": [{"type": "reject"}],
        "transports": {
            "containers-storage": {f"{STORAGE_SCOPE}{tag}": [{"type": "insecureAcceptAnything"}]}
        },
    }


@dataclasses.dataclass(frozen=True, slots=True)
class FixtureImage:
    digest: identifiers.ImageId
    config: identifiers.ImageId
    identity: str


@dataclasses.dataclass(frozen=True, slots=True)
class UpdateFixtureReport:
    run: identifiers.RunId
    images: Mapping[str, FixtureImage]
    files: Mapping[str, identifiers.Digest]
    public_key: identifiers.Digest
    archive: identifiers.Digest


def image_tag(run: identifiers.RunId, version: str) -> str:
    return f"{IMAGE_PREFIX}{run}:{version}"


def policy(public_key: bytes, run: identifiers.RunId) -> encoding.Document:
    """A containers policy that accepts only the fixture's own key for its own references."""
    scopes: dict[str, encoding.JsonValue] = {}
    for name, version in CASES:
        scopes[f"{FIXTURE_ROOT}/{run}/{name}"] = [
            {
                "type": "sigstoreSigned",
                "keyData": base64.b64encode(public_key).decode(),
                "signedIdentity": {
                    "type": "exactReference",
                    "dockerReference": image_tag(run, version),
                },
            }
        ]
    return {"default": [{"type": "reject"}], "transports": {"dir": scopes}}


def containerfile(version: str, *, parent: str, first: str) -> str:
    """Image A layers the reviewed configuration over the payload; B only carries its marker."""
    recipe = f"FROM {parent if version == 'a' else first}\n"
    if version == "a":
        recipe += (
            "COPY policy.json /etc/containers/policy.json\n"
            "COPY greenboot.conf /usr/share/apex/greenboot.conf\n"
            "COPY greenboot.conf /etc/greenboot/greenboot.conf\n"
            "COPY fix-grub-fragment.py /tmp/fix-grub-fragment.py\n"
            "RUN python3 /tmp/fix-grub-fragment.py "
            "/usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg "
            "> /usr/share/apex/greenboot-fragment.json && rm /tmp/fix-grub-fragment.py\n"
        )
    return recipe + "COPY marker.json /usr/share/apex/recovery-fixture.json\n"


def parse_report(document: Mapping[str, object]) -> UpdateFixtureReport:
    if document.get("status") != "PASS":
        raise _malformed(f"status is {document.get('status')!r}, not PASS")
    images = document.get("images")
    files = document.get("files")
    if not isinstance(images, dict) or set(images) != set(VERSIONS):
        raise _malformed("images must describe exactly a and b")
    if not isinstance(files, dict):
        raise _malformed("files must be a mapping")
    try:
        return UpdateFixtureReport(
            run=identifiers.RunId.parse(str(document.get("id", ""))),
            images={
                version: FixtureImage(
                    digest=identifiers.ImageId.parse(str(item["digest"])),
                    config=identifiers.ImageId.parse(str(item["config"])),
                    identity=str(item["identity"]),
                )
                for version, item in images.items()
            },
            files={str(name): identifiers.Digest(str(digest)) for name, digest in files.items()},
            public_key=identifiers.Digest(str(document.get("public_key_sha256", ""))),
            archive=identifiers.Digest(str(document.get("archive_sha256", ""))),
        )
    except (KeyError, TypeError, errors.Refusal) as error:
        raise _malformed(str(error)) from error


def _malformed(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FIXTURE_REPORT_MALFORMED, subject=detail)

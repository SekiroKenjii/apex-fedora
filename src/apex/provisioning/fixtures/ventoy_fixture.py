"""File-backed multiboot media, prepared in the builder from reviewed inputs only."""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Mapping

from apex.kernel import errors, identifiers, quantities, refusals

INPUTS = frozenset({"ventoy.tar.gz", "Apex-Live.iso", "Ubuntu.iso"})
ISOS = ("Apex-Live.iso", "Ubuntu.iso")
MEDIA_SIZE = quantities.Gib(16)
RESERVED = quantities.Mib(2048)
REQUIRED_FREE = quantities.Gib(27)
VERSION = re.compile(r"\d+\.\d+\.\d+")
PARTITION_TABLE = "dos"
PARTITIONS = 2
PACKAGES = ("parted", "exfatprogs", "qemu-img", "util-linux", "xz")
ARCHIVE = "ventoy.tar.gz"
UPSTREAM = "upstream"
RAW_IMAGE = "ventoy.raw"
IMAGE = "ventoy.qcow2"
MOUNT_POINT = "mount"
REPORT_NAME = "media.json"
REQUEST_NAME = "request.json"
INSTALLER = "Ventoy2Disk.sh"
MOUNT_OPTIONS = "nosuid,nodev,noexec"
FILESYSTEM = "exfat"
VERSION_LINE = "Ventoy Version in Disk: "


@dataclasses.dataclass(frozen=True, slots=True)
class VentoyRequest:
    files: Mapping[str, identifiers.Digest]
    version: str


@dataclasses.dataclass(frozen=True, slots=True)
class VentoyReport:
    request: VentoyRequest
    image: identifiers.Digest
    physical_media_accessed: bool


def parse_request(document: Mapping[str, object]) -> VentoyRequest:
    files = document.get("files")
    if not isinstance(files, dict) or set(files) != INPUTS:
        raise _malformed("expected exactly the reviewed Ventoy and two ISO inputs")
    try:
        digests = {str(name): identifiers.Digest(str(value)) for name, value in files.items()}
    except errors.Refusal as error:
        raise _malformed(f"input checksum: {error.subject}") from error
    version = str(document.get("ventoy_version", ""))
    if not VERSION.fullmatch(version):
        raise _malformed(f"invalid Ventoy version {version!r}")
    return VentoyRequest(files=digests, version=version)


def parse_report(document: Mapping[str, object]) -> VentoyReport:
    if document.get("status") != "PASS":
        raise _report(f"status is {document.get('status')!r}, not PASS")
    request = document.get("request")
    if not isinstance(request, dict):
        raise _report("the report must carry its request")
    if document.get("physical_media_accessed") is not False:
        raise _report("the report must state that no physical media was touched")
    try:
        image = identifiers.Digest(str(document.get("image_sha256", "")))
    except errors.Refusal as error:
        raise _report(f"image digest: {error.subject}") from error
    return VentoyReport(request=parse_request(request), image=image, physical_media_accessed=False)


def _malformed(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FIXTURE_REQUEST_MALFORMED, subject=detail)


def _report(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FIXTURE_REPORT_MALFORMED, subject=detail)

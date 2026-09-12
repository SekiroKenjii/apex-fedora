"""Disposable, formatted disks for installer preservation tests.

One disk carries three foreign filesystems with a sentinel each; the other is the empty
target. Neither boots anything, and the report says so.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from apex.kernel import errors, identifiers, quantities, refusals

OTHER_SIZE = quantities.Gib(4)
TARGET_SIZE = quantities.Gib(48)
OTHER_IMAGE = "other.qcow2"
TARGET_IMAGE = "target.qcow2"
PURPOSE = "installer disk preservation tests"


@dataclasses.dataclass(frozen=True, slots=True)
class Partition:
    index: int
    size: quantities.Mib
    kind: str
    filesystem: str
    label: str
    sentinel: str


PARTITIONS = (
    Partition(1, quantities.Mib(512), "U", "vfat", "APEX_EFI", "EFI/BOOT/apex-sentinel.txt"),
    Partition(
        2, quantities.Mib(1024), "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7", "ntfs-3g",
        "APEX_WINDOWS", "apex-sentinel.txt",
    ),
    Partition(3, quantities.Mib(2048), "L", "ext4", "APEX_LINUX", "apex-sentinel.txt"),
)


def layout() -> str:
    """The sfdisk script that carves the other disk."""
    lines = ["label: gpt"]
    lines.extend(
        f'size={item.size.value}M,type={item.kind},name="fixture-{_name(item)}"'
        for item in PARTITIONS
    )
    return "\n".join(lines) + "\n"


def _name(item: Partition) -> str:
    return {"vfat": "efi", "ntfs-3g": "windows", "ext4": "linux"}[item.filesystem]


@dataclasses.dataclass(frozen=True, slots=True)
class SentinelRecord:
    partition: int
    filesystem: str
    sentinel: str
    digest: identifiers.Digest


@dataclasses.dataclass(frozen=True, slots=True)
class InstallerFixtureReport:
    sentinels: tuple[SentinelRecord, ...]
    images: Mapping[str, identifiers.Digest]


def parse_report(document: Mapping[str, object]) -> InstallerFixtureReport:
    if document.get("bootable_existing_systems") is not False:
        raise _malformed("a fixture disk must declare that it boots nothing")
    records = document.get("partitions")
    digests = document.get("sha256")
    if not isinstance(records, list) or not isinstance(digests, dict):
        raise _malformed("partitions and sha256 are required")
    try:
        sentinels = tuple(
            SentinelRecord(
                partition=int(item["partition"]),
                filesystem=str(item["filesystem"]),
                sentinel=str(item["sentinel"]),
                digest=identifiers.Digest(str(item["sentinel_sha256"])),
            )
            for item in records
        )
        images = {str(name): identifiers.Digest(str(value)) for name, value in digests.items()}
    except (KeyError, TypeError, ValueError, errors.Refusal) as error:
        raise _malformed(str(error)) from error
    if [item.partition for item in sentinels] != [item.index for item in PARTITIONS]:
        raise _malformed("one sentinel per declared partition, in order")
    if set(images) != {OTHER_IMAGE, TARGET_IMAGE}:
        raise _malformed(f"expected digests for {OTHER_IMAGE} and {TARGET_IMAGE}")
    return InstallerFixtureReport(sentinels=sentinels, images=images)


def _malformed(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FIXTURE_REPORT_MALFORMED, subject=detail)

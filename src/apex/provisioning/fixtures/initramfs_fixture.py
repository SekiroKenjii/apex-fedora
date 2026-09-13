"""A corrupted initramfs on deployment B only, with A's boot path left untouched.

The entry parser and the rescue verdict are the parts of the older script that decide, and
they decide the same way here. The guest steps that remount, write and sync are the agent's.
"""

from __future__ import annotations

import dataclasses
import posixpath
import re
from collections.abc import Mapping

from apex.kernel import encoding, errors, hashing, identifiers, refusals

FIELDS = frozenset({"title", "version", "options", "linux", "initrd"})
BOOT_PREFIX = "/boot/ostree/"
FAULT_PATH = re.compile(r"/apex-initramfs-fault/[a-f0-9]{32}/bad\.img")
BOOTLINK = re.compile(r"/ostree/boot\.[01]/[a-z0-9_-]+/[a-f0-9]{64}/[0-9]+")
UNSAFE = re.compile(r"\s|[$;]")
OSTREE_OPTION = "ostree="
MARKER = b"APEX_BAD_INITRD\n"
MINIMUM_INITRAMFS_BYTES = 4096
SCOPE = "bootlink binding only, not recovery or boot acceptance"
BOOT_DIRECTORY = "/boot"
GRUB_CONFIG = "/boot/grub2/grub.cfg"
GRUB_ENVIRONMENT = "/boot/grub2/grubenv"
EFI_DIRECTORY = "/boot/efi/EFI"
BOOT_ENTRIES = "/boot/loader/entries"
FAULT_DIRECTORY = "/boot/apex-initramfs-fault"
TEST_DIRECTORY = "/var/lib/apex-initramfs-test"


@dataclasses.dataclass(frozen=True, slots=True)
class BootEntry:
    title: str
    version: str
    options: str
    linux: str
    initrd: str
    bootlink: str


@dataclasses.dataclass(frozen=True, slots=True)
class RescueBinding:
    safe_to_reboot_a: bool

    @property
    def reason(self) -> str:
        if self.safe_to_reboot_a:
            return "A uses the original initramfs"
        return "Rollback remapped the fault-bearing BLS entry to A; do not reboot"


def parse_entry(text: str, *, allow_fault: bool = False) -> BootEntry:
    fields = _fields(text)
    for key in ("linux", "initrd"):
        value = fields[key]
        if allow_fault and key == "initrd" and FAULT_PATH.fullmatch(value):
            continue
        if not _literal_boot_file(value):
            raise _malformed("expected a single literal boot file")
    links = [
        item.removeprefix(OSTREE_OPTION)
        for item in fields["options"].split()
        if item.startswith(OSTREE_OPTION)
    ]
    if len(links) != 1 or not BOOTLINK.fullmatch(links[0]):
        raise _malformed("expected one OSTree bootlink")
    return BootEntry(**fields, bootlink=links[0])


def modified_entry(text: str, new_initrd: str) -> str:
    entry = parse_entry(text)
    if not FAULT_PATH.fullmatch(new_initrd):
        raise errors.Refusal(refusals.RefusalReason.FIXTURE_PATH_NOT_ISOLATED, subject=new_initrd)
    old = f"initrd {entry.initrd}\n"
    if not text.endswith("\n") or text.count(old) != 1:
        raise _malformed("unknown initrd line layout")
    return text.replace(old, f"initrd {new_initrd}\n")


def corrupted_head(head: bytes) -> bytes:
    """The first bytes of the fault image: the marker over the start of the real one."""
    return MARKER + head[len(MARKER) :]


def require_isolated(a: BootEntry, b: BootEntry, *, a_initrd: str, b_initrd: str) -> None:
    """A fault on B must not be reachable from A through a shared boot identity."""
    shared_link = posixpath.dirname(a.bootlink) == posixpath.dirname(b.bootlink)
    if shared_link or a_initrd == b_initrd:
        raise errors.Refusal(
            refusals.RefusalReason.FIXTURE_PATH_NOT_ISOLATED,
            subject="shared boot identity can retarget the fault onto A after rollback",
            remedy="use a new isolated fixture",
        )


def rescue_binding(entries: Mapping[str, BootEntry]) -> RescueBinding:
    if set(entries) != {"a", "b"}:
        raise _malformed("both deployment mappings are required")
    return RescueBinding(safe_to_reboot_a=entries["a"].initrd.startswith(BOOT_PREFIX))


def plan_digest(plan: encoding.Document) -> identifiers.Digest:
    return hashing.digest_bytes(encoding.canonical(plan))


def _fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition(" ")
        if not separator or key in fields:
            raise _malformed("ambiguous BLS fields")
        fields[key] = value
    if set(fields) != FIELDS:
        raise _malformed("review this BLS format before injecting a fault")
    return fields


def _literal_boot_file(value: str) -> bool:
    parts = value.split("/")
    return value.startswith(BOOT_PREFIX) and ".." not in parts and not UNSAFE.search(value)


def _malformed(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FIXTURE_ENTRY_MALFORMED, subject=detail)

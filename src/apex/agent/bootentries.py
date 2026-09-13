"""The boot entries of an installed guest and the files they name, bound to deployments.

Each BLS entry resolves through its OSTree bootlink to exactly one deployment, whose marker
says which fixture version it is. Every boot input a fault must leave alone is fingerprinted
by content and identity, so an injection can tell when anything else moved.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, deployments
from apex.config import defaults
from apex.kernel import encoding, safepaths
from apex.ports import files
from apex.provisioning.fixtures import initramfs_fixture

MARKER = "usr/share/apex/recovery-fixture.json"
ENTRY_SUFFIX = ".conf"
BOOT_FILES = ("linux", "initrd")
VERSIONS = ("a", "b")


@dataclasses.dataclass(frozen=True, slots=True)
class Bound:
    version: str
    path: str
    text: str
    entry: initramfs_fixture.BootEntry
    deployment: str
    marker: encoding.Document
    boot_files: Mapping[str, str]

    def document(self) -> encoding.Document:
        return {
            "path": self.path,
            "text": self.text,
            "fields": dataclasses.asdict(self.entry),
            "files": dict(self.boot_files),
            "deployment": self.deployment,
            "marker": dict(self.marker),
        }


def fingerprint(ports: agentports.AgentPorts, path: safepaths.SafePath) -> encoding.Document:
    seen = ports.files.inspect(path)
    if seen.kind is not files.EntryKind.REGULAR:
        raise deployments.unexpected(f"expected a regular final file: {path}")
    identity = ports.files.identity(path)
    return {
        "sha256": ports.digests.file(path).hex,
        "size": identity.size,
        "inode": identity.inode,
        "device": identity.device,
        "links": identity.links,
        "mode": seen.mode.value,
        "uid": seen.owner,
        "gid": seen.group,
    }


def marker(ports: agentports.AgentPorts, deployment: safepaths.SafePath) -> encoding.Document:
    text = ports.files.read_bytes(deployment / MARKER, limit=defaults.DOCUMENT_LIMIT.value)
    return deployments.document(text.decode(errors="replace"), what="the deployment marker")


def _entry_paths(ports: agentports.AgentPorts) -> list[safepaths.SafePath]:
    directory = safepaths.SafePath(Path(initramfs_fixture.BOOT_ENTRIES))
    found = [
        directory / item.relative
        for item in ports.files.list_directory(directory)
        if item.relative.endswith(ENTRY_SUFFIX)
    ]
    if len(found) != 2:
        raise deployments.unexpected("expected exactly two BLS entries")
    return found


def _inside_boot(path: safepaths.SafePath) -> bool:
    return str(path).startswith(initramfs_fixture.BOOT_DIRECTORY + "/")


def boot_files(ports: agentports.AgentPorts, entry: initramfs_fixture.BootEntry) -> dict[str, str]:
    """The kernel and initramfs the entry names, resolved below the boot filesystem."""
    found: dict[str, str] = {}
    for key, value in ((BOOT_FILES[0], entry.linux), (BOOT_FILES[1], entry.initrd)):
        resolved = ports.files.resolve(
            safepaths.SafePath(Path(initramfs_fixture.BOOT_DIRECTORY) / value.lstrip("/"))
        )
        named = ports.files.resolve(safepaths.SafePath(Path(value)))
        same = ports.files.identity(resolved) == ports.files.identity(named)
        if not _inside_boot(resolved) or not same:
            raise deployments.unexpected("ambiguous boot path mapping")
        found[key] = str(resolved)
    return found


def _bind_one(
    ports: agentports.AgentPorts,
    path: safepaths.SafePath,
    targets: Mapping[str, safepaths.SafePath],
    *,
    allow_fault: bool,
) -> Bound:
    text = ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value).decode()
    entry = initramfs_fixture.parse_entry(text, allow_fault=allow_fault)
    destination = ports.files.resolve(safepaths.SafePath(Path(entry.bootlink)))
    matches = [version for version, target in targets.items() if str(destination) == str(target)]
    if len(matches) != 1:
        raise deployments.unexpected("BLS entry does not resolve to exactly one deployment")
    found = marker(ports, destination)
    if found.get("version") != matches[0]:
        raise deployments.unexpected("deployment marker mismatch")
    actual = ports.files.resolve(path)
    if ports.files.inspect(path).kind is files.EntryKind.SYMLINK or not _inside_boot(actual):
        raise deployments.unexpected("BLS entry escapes the boot filesystem")
    return Bound(
        version=matches[0],
        path=str(actual),
        text=text,
        entry=entry,
        deployment=str(destination),
        marker=found,
        boot_files={} if allow_fault else boot_files(ports, entry),
    )


def bind(
    ports: agentports.AgentPorts,
    targets: Mapping[str, safepaths.SafePath],
    *,
    allow_fault: bool = False,
) -> dict[str, Bound]:
    """Both entries, each bound to the one deployment its bootlink reaches."""
    bound: dict[str, Bound] = {}
    for path in _entry_paths(ports):
        one = _bind_one(ports, path, targets, allow_fault=allow_fault)
        if one.version in bound:
            raise deployments.unexpected("two BLS entries resolve to one deployment")
        bound[one.version] = one
    if set(bound) != set(VERSIONS):
        raise deployments.unexpected("both deployment mappings are required")
    return bound


def protected(
    ports: agentports.AgentPorts, bound: Mapping[str, Bound]
) -> dict[str, encoding.JsonValue]:
    """Every boot input the fault must leave alone, fingerprinted."""
    efi = safepaths.SafePath(Path(initramfs_fixture.EFI_DIRECTORY))
    named = [
        safepaths.SafePath(Path(initramfs_fixture.GRUB_CONFIG)),
        safepaths.SafePath(Path(initramfs_fixture.GRUB_ENVIRONMENT)),
        *(
            efi / item.relative
            for item in ports.files.list_tree(efi)
            if item.kind is files.EntryKind.REGULAR
        ),
    ]
    for one in bound.values():
        named.extend(safepaths.SafePath(Path(value)) for value in one.boot_files.values())
        named.append(safepaths.SafePath(Path(one.path)))
    return {str(path): fingerprint(ports, path) for path in named}


def unchanged(
    ports: agentports.AgentPorts, expected: Mapping[str, encoding.JsonValue], *, except_for: str
) -> None:
    """Refuse when any protected input but the named one differs from its fingerprint."""
    for name, identity in expected.items():
        if name != except_for and fingerprint(ports, safepaths.SafePath(Path(name))) != identity:
            raise deployments.unexpected(f"a protected boot input changed: {name}")

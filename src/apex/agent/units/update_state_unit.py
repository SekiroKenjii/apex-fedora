"""What an installed guest is running, read before and after an update operation.

This is the older update tool's opening: the boot identifier, the package versions, the
digests of every kernel and initramfs under the modules tree, the deployment status, the
digest of the consumer policy and the fixture marker, each read once through a port.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, deployments, guestguard, observing, units
from apex.config import defaults
from apex.kernel import commands, encoding, identifiers, safepaths
from apex.ports import files
from apex.provisioning.fixtures import update_fixture

VERSIONS = commands.Argv.of("rpm", "-q", "bootc", "greenboot", "kernel-core", "gnome-shell")
KERNEL_FILES = ("vmlinuz", "initramfs.img")


def kernel_inputs(ports: agentports.AgentPorts) -> dict[str, encoding.JsonValue]:
    """The digest of every kernel and initramfs under the modules tree, by path."""
    modules = safepaths.SafePath(Path(update_fixture.MODULES_DIRECTORY))
    found: dict[str, encoding.JsonValue] = {}
    for entry in ports.files.list_directory(modules):
        if entry.kind is not files.EntryKind.DIRECTORY:
            continue
        for name in KERNEL_FILES:
            path = modules / entry.relative / name
            if ports.files.exists(path):
                found[str(path)] = ports.digests.file(path).hex
    return found


def marker(ports: agentports.AgentPorts) -> encoding.JsonValue:
    path = safepaths.SafePath(Path(update_fixture.RECOVERY_MARKER))
    if not ports.files.exists(path):
        return None
    text = ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)
    return deployments.document(text.decode(errors="replace"), what="the fixture marker")


def run(
    ports: agentports.AgentPorts,
    *,
    arguments: Mapping[str, encoding.JsonValue],  # noqa: ARG001
) -> encoding.Document:
    guestguard.require_installed(ports)
    boot_id = ports.files.read_bytes(
        safepaths.SafePath(Path(defaults.BOOT_ID)), limit=defaults.DOCUMENT_LIMIT.value
    )
    ports.digests.forget()
    return {
        "boot_id": boot_id.decode().strip(),
        "versions": observing.program(ports, VERSIONS),
        "kernel_inputs": kernel_inputs(ports),
        "bootc": deployments.read(ports).document,
        "policy_sha256": ports.digests.file(
            safepaths.SafePath(Path(update_fixture.BUILDER_POLICY))
        ).hex,
        "marker": marker(ports),
    }


units.declare(units.Unit(id=identifiers.ProbeId("update.state"), run=run))

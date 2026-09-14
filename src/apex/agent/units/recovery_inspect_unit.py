"""Read the boot state of an installed guest before and after a recovery operation.

This is the older recovery tool's inspection: the same programs in the same order, each
recorded with its exit code and both streams, none of them judged here.
"""

from __future__ import annotations

from collections.abc import Mapping

from apex.agent import agentports, guestguard, observing, units
from apex.config import defaults
from apex.kernel import commands, encoding, identifiers
from apex.provisioning.fixtures import initramfs_fixture, recovery_fixture, update_fixture

COMMANDS: Mapping[str, commands.Argv] = {
    "bootc": commands.Argv.of("bootc", "status", "--json"),
    "packages": commands.Argv.of("rpm", "-q", "bootupd", "greenboot", "bootc"),
    "grub_environment": commands.Argv.of("grub2-editenv", "-", "list"),
    "grub_config": commands.Argv.of("cat", initramfs_fixture.GRUB_CONFIG),
    "greenboot_config": commands.Argv.of("cat", recovery_fixture.GREENBOOT_CONFIG),
    "boot_id": commands.Argv.of("cat", defaults.BOOT_ID),
    "units": commands.Argv.of(
        "systemctl", "show", "gdm", "greenboot-healthcheck", "-p", "ActiveState", "-p", "Result"
    ),
    "boot_files": commands.Argv.of(
        "sh",
        "-c",
        f"sha256sum {initramfs_fixture.GRUB_CONFIG} {initramfs_fixture.GRUB_ENVIRONMENT} "
        f"/boot/bootupd-state.json {initramfs_fixture.EFI_DIRECTORY}/*/* "
        f"{initramfs_fixture.BOOT_ENTRIES}/*",
    ),
    "kernel_inputs": commands.Argv.of(
        "sh",
        "-c",
        f"sha256sum {update_fixture.MODULES_DIRECTORY}/*/vmlinuz "
        f"{update_fixture.MODULES_DIRECTORY}/*/initramfs.img "
        f"/var/home/{defaults.TEST_ACCOUNT}/{defaults.UPDATE_SENTINEL_NAME}",
    ),
}


def run(
    ports: agentports.AgentPorts,
    *,
    arguments: Mapping[str, encoding.JsonValue],  # noqa: ARG001
) -> encoding.Document:
    guestguard.require_installed(ports)
    return observing.programs(ports, COMMANDS)


units.declare(units.Unit(id=identifiers.ProbeId("recovery.inspect"), run=run))

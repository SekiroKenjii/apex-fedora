"""Make one diagnostic change to an installed disposable guest, never a release migration.

This is `guest/recovery-fixture.py` step for step: the exact newline repair of the installed
GRUB configuration, the observer armed around gdm and the health check for the next boot of
B, or the one-retry variant of the greenboot configuration. Each keeps what it replaced under
the run's directory, and each runs in the caller's private mount namespace.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, deployments, guestguard, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, quantities, refusals, safepaths
from apex.ports import files
from apex.provisioning.fixtures import initramfs_fixture, recovery_fixture, update_fixture

REPAIR_GRUB = "repair-grub"
ARM_GDM = "arm-gdm"
RETRY_CONFIG = "retry-config"
ACTIONS = (REPAIR_GRUB, ARM_GDM, RETRY_CONFIG)
RUN_ID = re.compile(r"[a-f0-9]{32}")
HEX_64 = re.compile(r"[a-f0-9]{64}")
PRIVATE_DIRECTORY = quantities.FileMode(0o700)
PRIVATE_FILE = quantities.FileMode(0o600)
PROGRAM_MODE = quantities.FileMode(0o700)
REMOUNT = commands.Argv.of("mount", "-o", "remount,rw", initramfs_fixture.BOOT_DIRECTORY)
RELOAD = commands.Argv.of("systemctl", "daemon-reload")
OBSERVER = "observe.py"
TEMPORARY_PREFIX = ".apex-grub-"
PASS = "PASS"


def _argument(arguments: Mapping[str, encoding.JsonValue], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject=f"{name} must be a string"
        )
    return value


def _require_guest(ports: agentports.AgentPorts, expected: str) -> None:
    guestguard.require_installed(ports)
    deployments.require_private_mounts()
    deployments.require_components(ports, recovery_fixture.EXPECTED_COMPONENTS)
    status = deployments.read(ports)
    status.require_booted(expected)
    status.require_healthy_pair()


def _regular(ports: agentports.AgentPorts, path: safepaths.SafePath) -> bytes:
    if ports.files.inspect(path).kind is not files.EntryKind.REGULAR:
        raise deployments.unexpected(f"{path}: not a regular file")
    return ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)


def repair_grub(
    ports: agentports.AgentPorts, preimage: str, report: safepaths.SafePath
) -> encoding.Document:
    """The reviewed newline repair, applied only over the exact installed preimage."""
    target = safepaths.SafePath(Path(initramfs_fixture.GRUB_CONFIG))
    if not HEX_64.fullmatch(preimage):
        raise deployments.unexpected("an exact regular-file preimage is required")
    before = _regular(ports, target)
    if ports.digests.file(target).hex != preimage:
        raise deployments.unexpected("installed GRUB preimage changed")
    fragment = ports.files.read_bytes(
        safepaths.SafePath(Path(update_fixture.FRAGMENT)), limit=defaults.DOCUMENT_LIMIT.value
    )
    after = recovery_fixture.repaired_config(before, fragment)
    ports.files.write_atomic(report / "grub.cfg.before", before, mode=PRIVATE_FILE)
    environment = safepaths.SafePath(Path(initramfs_fixture.GRUB_ENVIRONMENT))
    environment_before = ports.files.read_bytes(environment, limit=defaults.DOCUMENT_LIMIT.value)
    deployments.output(ports, REMOUNT)
    temporary = safepaths.SafePath(target.path.parent / f"{TEMPORARY_PREFIX}{report.path.name}")
    ports.files.write_atomic(temporary, after, mode=ports.files.mode_of(target))
    deployments.output(ports, commands.Argv.of("grub2-script-check", str(temporary)))
    deployments.output(ports, commands.Argv.of("chcon", f"--reference={target}", str(temporary)))
    if ports.files.read_bytes(target, limit=defaults.DOCUMENT_LIMIT.value) != before:
        raise deployments.unexpected("GRUB changed during validation")
    ports.files.replace(temporary, target)
    deployments.output(ports, commands.Argv.of("sync", "-f", str(target)))
    environment_after = ports.files.read_bytes(environment, limit=defaults.DOCUMENT_LIMIT.value)
    if environment_after != environment_before:
        raise deployments.unexpected("unexpected GRUB environment change")
    ports.digests.forget()
    return {
        "status": PASS, "scope": "VM-only exact newline diagnostic repair",
        "production_migration": "BLOCKED", "before_sha256": preimage,
        "after_sha256": ports.digests.file(target).hex, "grubenv_unchanged": True,
    }


def arm_gdm(
    ports: agentports.AgentPorts, bad: str, report: safepaths.SafePath
) -> encoding.Document:
    """The observer program and the drop-ins that run it on the next boot of B."""
    program = report / OBSERVER
    source = recovery_fixture.observer_program(
        identifiers.ImageId.parse(bad), safepaths.RemotePath(str(report))
    )
    ports.files.write_atomic(program, source.encode(), mode=PROGRAM_MODE)
    for unit, text in recovery_fixture.unit_overrides(safepaths.RemotePath(str(program))).items():
        directory = safepaths.SafePath(Path(recovery_fixture.SYSTEMD_UNITS) / f"{unit}.d")
        ports.files.make_directory(directory, mode=quantities.FileMode(0o755))
        drop_in = directory / recovery_fixture.DROP_IN
        if ports.files.exists(drop_in):
            raise deployments.unexpected(f"{drop_in}: the fault is already armed")
        ports.files.write_atomic(drop_in, text.encode(), mode=quantities.FileMode(0o644))
    deployments.output(ports, RELOAD)
    return {
        "status": PASS, "scope": "Fault armed for next B boot only, not acceptance",
        "bad_digest": bad, "program_sha256": ports.digests.file(program).hex,
        "directory": str(report),
    }


def retry_config(ports: agentports.AgentPorts, report: safepaths.SafePath) -> encoding.Document:
    """The one-retry variant of the greenboot configuration, over the two-retry original."""
    path = safepaths.SafePath(Path(recovery_fixture.GREENBOOT_CONFIG))
    before = _regular(ports, path)
    after = recovery_fixture.retry_config(before)
    ports.files.write_atomic(report / "greenboot.conf.before", before, mode=PRIVATE_FILE)
    ports.files.write_atomic(path, after, mode=ports.files.mode_of(path))
    deployments.output(ports, commands.Argv.of("sync", "-f", str(path)))
    ports.digests.forget()
    return {
        "status": PASS, "scope": "VM configuration variation, not rebuilt image",
        "before_sha256": ports.digests.file(report / "greenboot.conf.before").hex,
        "after_sha256": ports.digests.file(path).hex,
    }


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    action = _argument(arguments, "action")
    run_id = _argument(arguments, "run_id")
    if action not in ACTIONS or not RUN_ID.fullmatch(run_id):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject=f"{action} under {run_id}"
        )
    _require_guest(ports, _argument(arguments, "expected_digest"))
    report = safepaths.SafePath(Path(recovery_fixture.TEST_DIRECTORY) / run_id)
    if ports.files.exists(report):
        raise deployments.unexpected(f"{report}: the run directory already exists")
    ports.files.make_directory(report, mode=PRIVATE_DIRECTORY)
    if action == REPAIR_GRUB:
        result = repair_grub(ports, _argument(arguments, "preimage"), report)
    elif action == ARM_GDM:
        result = arm_gdm(ports, _argument(arguments, "bad_digest"), report)
    else:
        result = retry_config(ports, report)
    ports.files.write_atomic(report / "result.json", encoding.canonical(result), mode=PRIVATE_FILE)
    return result


units.declare(units.Unit(id=identifiers.ProbeId("fixture.recovery"), run=run))

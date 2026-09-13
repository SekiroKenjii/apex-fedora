"""Verify the installer-generated recovery configuration without changing the guest.

This is `guest/installed-recovery-probe.py`: the booted deployment must be the expected
candidate, the installed GRUB file must be exactly bootupd's assembly of the image's
fragments, the greenboot fragment must end at its separator, both retry configurations must
hash to the built fixture's digest and carry the one-retry preset, and SELinux must enforce.
A guest that is not the expected one is refused; a configuration that differs is a report
that says so.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, grubstatic, guestguard, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, refusals, safepaths

PASS = "PASS"
FAIL = "FAIL"
SCOPE = "Installed recovery configuration, not fault acceptance"
EXPECTED_ARGUMENT = "expected_digest"
CONFIG_ARGUMENT = "config_sha256"
HEX_64 = re.compile(r"[a-f0-9]{64}")
STATIC = safepaths.SafePath(Path("/usr/lib/bootupd/grub2-static"))
INSTALLED_GRUB = safepaths.SafePath(Path("/boot/grub2/grub.cfg"))
CONFIGURATIONS = ("/etc/greenboot/greenboot.conf", "/usr/share/apex/greenboot.conf")
PRESET = "GREENBOOT_MAX_BOOT_ATTEMPTS=1\n"
ENFORCING = "Enforcing"
BOOTC_STATUS = commands.Argv.of("bootc", "status", "--format", "json")
VERSIONS = commands.Argv.of("rpm", "-q", "bootupd", "greenboot", "bootc")
GRUB_ENVIRONMENT = commands.Argv.of("grub2-editenv", "-", "list")
ENFORCEMENT = commands.Argv.of("getenforce")


class Differs(Exception):
    """The installed configuration is not the reviewed one; reported, never raised past."""


def _argument(arguments: Mapping[str, encoding.JsonValue], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject=f"{name} must be given"
        )
    return value


def _output(ports: agentports.AgentPorts, argv: commands.Argv) -> str:
    completed = ports.processes.run(
        argv, deadline=defaults.PROBE_DEADLINE, limit=commands.OutputLimit.default()
    )
    if not completed.succeeded:
        raise Differs(f"{argv.arguments[0]} exited with {completed.exit_code}")
    return completed.stdout.decode(errors="replace")


def _read(ports: agentports.AgentPorts, path: safepaths.SafePath) -> bytes:
    return ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)


def _nested(document: encoding.JsonValue, *keys: str) -> encoding.JsonValue:
    current = document
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _booted(ports: agentports.AgentPorts, expected: identifiers.Digest) -> encoding.JsonValue:
    status = encoding.parse_document(_output(ports, BOOTC_STATUS).encode())
    digest = _nested(status, "status", "booted", "image", "imageDigest")
    if digest != str(expected):
        raise guestguard.refuse("the booted deployment is not the expected candidate")
    return status


def _fragments(ports: agentports.AgentPorts) -> dict[str, bytes]:
    directory = STATIC / "configs.d"
    return {
        entry.relative: _read(ports, directory / entry.relative)
        for entry in ports.files.list_directory(directory)
        if entry.relative.endswith(grubstatic.FRAGMENT_SUFFIX)
    }


def _verify(
    ports: agentports.AgentPorts, report: dict[str, encoding.JsonValue], config: str
) -> None:
    fragments = _fragments(ports)
    installed = _read(ports, INSTALLED_GRUB)
    report["grub_sha256"] = hashlib.sha256(installed).hexdigest()
    generated = grubstatic.assemble(_read(ports, STATIC / "grub-static-pre.cfg"), fragments)
    if installed != generated:
        raise Differs("Installed GRUB differs from the image static configuration")
    report["grub_matches_image_assembly"] = True
    greenboot = fragments.get(grubstatic.GREENBOOT_FRAGMENT, b"")
    if not greenboot.endswith(grubstatic.SEPARATOR):
        raise Differs("Missing GRUB fragment separator")
    hashes = {
        name: hashlib.sha256(_read(ports, safepaths.SafePath(Path(name)))).hexdigest()
        for name in CONFIGURATIONS
    }
    report["config_sha256"] = dict(hashes)
    if any(value != config for value in hashes.values()):
        raise Differs("Retry configuration differs from the built fixture")
    text = _read(ports, safepaths.SafePath(Path(CONFIGURATIONS[0]))).decode(errors="replace")
    if PRESET not in text:
        raise Differs("Expected the one-retry preset")
    if _output(ports, ENFORCEMENT).strip() != ENFORCING:
        raise Differs("SELinux is not enforcing")


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    guestguard.require_installed(ports)
    expected = identifiers.Digest.parse(_argument(arguments, EXPECTED_ARGUMENT))
    config = _argument(arguments, CONFIG_ARGUMENT)
    if not HEX_64.fullmatch(config):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject=f"{CONFIG_ARGUMENT} is not a digest"
        )
    status = _booted(ports, expected)
    report: dict[str, encoding.JsonValue] = {
        "status": FAIL,
        "scope": SCOPE,
        "digest": str(expected),
        "boot_id": _read(ports, safepaths.SafePath(Path(defaults.BOOT_ID))).decode().strip(),
        "grub_matches_image_assembly": False,
        "guest_writes": False,
        "bootc": status,
    }
    try:
        _verify(ports, report, config)
        report["versions"] = _output(ports, VERSIONS)
        report["grubenv"] = _output(ports, GRUB_ENVIRONMENT)
    except Differs as difference:
        report["failure"] = str(difference)
        return report
    report["status"] = PASS
    return report


units.declare(units.Unit(id=identifiers.ProbeId("recovery.installed"), run=run))

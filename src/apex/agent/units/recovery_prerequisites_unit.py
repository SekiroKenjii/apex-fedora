"""Inspect recovery prerequisites in an installed test guest without injecting a fault.

This is `guest/recovery-probe.py`: the same programs, the same files, and the same reading
of the deployment status. Two distinct deployments are a prerequisite, never proof; the
report says NOT TESTED where the older one did and BLOCKED where a prerequisite is missing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from apex.agent import agentports, guestguard, observing, units
from apex.kernel import commands, encoding, identifiers

NOT_TESTED = "NOT TESTED"
BLOCKED = "BLOCKED"
SCOPE = "Read-only installed VM recovery prerequisites"
NOTE = "Two deployments alone do not prove trust, health or automatic recovery"
COMMANDS: Mapping[str, commands.Argv] = {
    "bootc": commands.Argv.of("bootc", "status", "--format", "json"),
    "packages": commands.Argv.of(
        "rpm", "-q", "bootc", "greenboot", "grub2-common", "grub2-tools-minimal"
    ),
    "units": commands.Argv.of(
        "systemctl",
        "cat",
        "greenboot-healthcheck.service",
        "greenboot-set-rollback-trigger.service",
    ),
    "unit-state": commands.Argv.of(
        "systemctl",
        "show",
        "greenboot-healthcheck.service",
        "greenboot-set-rollback-trigger.service",
        "-p",
        "ActiveState",
        "-p",
        "SubState",
        "-p",
        "Result",
        "-p",
        "UnitFileState",
    ),
    "grub-environment": commands.Argv.of("grub2-editenv", "-", "list"),
    "greenboot-journal": commands.Argv.of(
        "journalctl",
        "-b",
        "-u",
        "greenboot-healthcheck.service",
        "-u",
        "greenboot-set-rollback-trigger.service",
        "--no-pager",
        "-n",
        "300",
    ),
    "failed-units": commands.Argv.of("systemctl", "--failed", "--no-legend", "--no-pager"),
    "selinux": commands.Argv.of("getenforce"),
}
FILES = (
    "/etc/greenboot/greenboot.conf",
    "/boot/grub2/grub.cfg",
    "/usr/lib/bootupd/grub2-static/configs.d/08_greenboot.cfg",
    "/usr/lib/greenboot/check/required.d/20-apex-system.sh",
)


def _digest_of(deployments: Mapping[str, object], slot: str) -> str | None:
    deployment = deployments.get(slot)
    image = deployment.get("image") if isinstance(deployment, dict) else None
    digest = image.get("imageDigest") if isinstance(image, dict) else None
    return digest if isinstance(digest, str) and digest else None


def prerequisites(status: object) -> encoding.Document:
    """Blocked without two distinct deployments; otherwise not tested, never passed."""
    deployments = status.get("status", {}) if isinstance(status, dict) else {}
    if not isinstance(deployments, dict):
        deployments = {}
    reasons = [
        f"No {slot} image digest"
        for slot in ("booted", "rollback")
        if _digest_of(deployments, slot) is None
    ]
    if not reasons and _digest_of(deployments, "booted") == _digest_of(deployments, "rollback"):
        reasons.append("Booted and rollback images are not distinct test deployments")
    return {"status": BLOCKED if reasons else NOT_TESTED, "reasons": reasons, "note": NOTE}


def _status(observation: encoding.JsonValue) -> encoding.Document:
    if not isinstance(observation, dict) or observation.get("returncode") != 0:
        return {"status": BLOCKED, "reasons": ["bootc status failed"], "note": NOTE}
    try:
        return prerequisites(json.loads(str(observation.get("stdout", ""))))
    except json.JSONDecodeError:
        return {"status": BLOCKED, "reasons": ["bootc status is not JSON"], "note": NOTE}


def run(
    ports: agentports.AgentPorts,
    *,
    arguments: Mapping[str, encoding.JsonValue],  # noqa: ARG001
) -> encoding.Document:
    # This probe takes no arguments; the shape is the unit contract and every unit keeps it.
    guestguard.require_installed(ports)
    observations = observing.programs(ports, COMMANDS)
    return {
        "scope": SCOPE,
        "recovery_acceptance": NOT_TESTED,
        "prerequisites": _status(observations["bootc"]),
        "commands": observations,
        "files": observing.texts(ports, FILES),
    }


units.declare(units.Unit(id=identifiers.ProbeId("recovery.prerequisites"), run=run))

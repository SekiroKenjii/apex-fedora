"""Exercise the unmodified guard with a kernel-denied read-only lock in the initramfs.

This is `guest/live-lock-fault.py`: the guest must be at the pre-mount breakpoint with the
reviewed guard on disk, the sentinel fixture is made writable behind a stopped udev queue,
the guard is run in a child with `CAP_SYS_ADMIN` dropped so the kernel denies its lock, and
the latch it must set is read back. The fixture is restored whatever happened, and the report
says what happened; the host decides what it proves.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
import shlex
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, blockdevices, guestguard, livefixtures, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, refusals, safepaths

NOT_TESTED = "NOT TESTED"
PASS = "PASS"
FAIL = "FAIL"
SCOPE = "Initramfs guard with CAP_SYS_ADMIN removed from child"
GUARD_ARGUMENT = "guard_sha256"
HEX_64 = re.compile(r"[a-f0-9]{64}")
CAPABILITY_LINES = re.compile(r"(CapEff|CapBnd):\s*([0-9a-f]+)")
CAPABILITY_NAMES = frozenset({"CapEff", "CapBnd"})
DENIED = "Permission denied"
LOCALE = {"LC_ALL": "C"}
SETTLE = commands.Argv.of("udevadm", "settle", "--timeout=15")
STOP_QUEUE = commands.Argv.of("udevadm", "control", "--stop-exec-queue")
START_QUEUE = commands.Argv.of("udevadm", "control", "--start-exec-queue")
GUARD = safepaths.SafePath(Path(defaults.LIVE_GUARD))
LATCH = safepaths.SafePath(Path(defaults.PROTECTION_LATCH))
ATTRIBUTE_LIMIT = 16


class Halt(Exception):
    """A step that did not go as the fault needs; recorded, never raised past the cleanup."""


@dataclasses.dataclass(slots=True)
class Run:
    ports: agentports.AgentPorts
    report: dict[str, encoding.JsonValue]
    log: list[encoding.JsonValue]

    def invoke(
        self, argv: commands.Argv, *, check: bool = True, restricted: bool = False
    ) -> commands.CompletedRun:
        completed = self.ports.processes.run(
            argv,
            deadline=defaults.PROBE_DEADLINE,
            limit=commands.OutputLimit.default(),
            variables=LOCALE,
            dropping=frozenset({commands.Capability.SYS_ADMIN}) if restricted else frozenset(),
        )
        self.log.append(
            {
                "argv": list(argv),
                "restricted_child": restricted,
                "returncode": completed.exit_code,
                "stdout": completed.stdout.decode(errors="replace"),
                "stderr": completed.stderr.decode(errors="replace"),
            }
        )
        if check and not completed.succeeded:
            raise Halt(f"fixture command failed: {' '.join(argv)}")
        return completed

    def read_only(self, name: str) -> str:
        attribute = blockdevices.SYSFS_BLOCK / name / "ro"
        return self.ports.files.read_bytes(attribute, limit=ATTRIBUTE_LIMIT).decode().strip()


def _guard_digest(ports: agentports.AgentPorts, expected: object) -> str:
    if not isinstance(expected, str) or not HEX_64.fullmatch(expected):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"{GUARD_ARGUMENT} must be the reviewed guard's digest",
        )
    observed = hashlib.sha256(
        ports.files.read_bytes(GUARD, limit=defaults.DOCUMENT_LIMIT.value)
    ).hexdigest()
    if observed != expected:
        raise guestguard.refuse("the guard differs from the reviewed source")
    return observed


def _denied(
    completed: commands.CompletedRun, caps: Mapping[str, str], *, readonly: str, latched: bool
) -> bool:
    """The older `validate_denial`, as a question rather than an exception."""
    return (
        not completed.succeeded
        and DENIED in completed.stderr.decode(errors="replace")
        and set(caps) == CAPABILITY_NAMES
        and not any(_holds_admin(value) for value in caps.values())
        and readonly == "0"
        and latched
    )


def _holds_admin(mask: str) -> bool:
    return bool(int(mask, 16) & (1 << commands.Capability.SYS_ADMIN))


def _exercise(run: Run, target: str) -> None:
    device = f"/dev/{target}"
    run.invoke(STOP_QUEUE)
    run.report["queue_stopped"] = True
    run.invoke(commands.Argv.of("blockdev", "--setrw", device))
    before = run.read_only(target)
    if before != "0":
        raise Halt("fixture was not writable before the denied lock")
    run.report["ro_before_denial"] = before
    script = (
        'sed -n "/^CapEff:/p; /^CapBnd:/p" /proc/self/status; exec '
        + shlex.quote(str(GUARD))
        + " "
        + shlex.quote(device)
    )
    completed = run.invoke(commands.Argv.of("/bin/sh", "-c", script), check=False, restricted=True)
    caps = dict(CAPABILITY_LINES.findall(completed.stdout.decode(errors="replace")))
    run.report["child_capabilities"] = caps
    run.report["ro_after_denial"] = run.read_only(target)
    latched = run.ports.files.exists(LATCH)
    run.report["failure_latched"] = latched
    denied = _denied(completed, caps, readonly=str(run.report["ro_after_denial"]), latched=latched)
    run.report["kernel_denial"] = PASS if denied else FAIL


def _restore(run: Run, target: str) -> None:
    device = f"/dev/{target}"
    try:
        run.invoke(commands.Argv.of("blockdev", "--setro", device), check=False)
        run.report["ro_after_cleanup"] = run.read_only(target)
    finally:
        run.invoke(START_QUEUE, check=False)


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    guestguard.require_initramfs(ports)
    digest = _guard_digest(ports, arguments.get(GUARD_ARGUMENT))
    inventory = livefixtures.Inventory.take(ports, matching=livefixtures.VIRTIO_NAME)
    livefixtures.require_live_fixture(inventory)
    target = next(item for item in inventory.devices if item.serial == livefixtures.OTHER_SERIAL)
    report: dict[str, encoding.JsonValue] = {
        "status": FAIL,
        "scope": SCOPE,
        "guard_sha256": digest,
        "target": target.document(),
        "commands": [],
        "boot_rejection": NOT_TESTED,
        "whole_disk_comparison": NOT_TESTED,
        "queue_stopped": False,
    }
    held = Run(ports=ports, report=report, log=[])
    report["commands"] = held.log
    held.invoke(SETTLE)
    try:
        _exercise(held, target.name)
    except Halt as halt:
        report["failure"] = str(halt)
    finally:
        if report["queue_stopped"]:
            _restore(held, target.name)
    if report.get("kernel_denial") == PASS and report.get("ro_after_cleanup") == "1":
        report["status"] = PASS
    return report


units.declare(units.Unit(id=identifiers.ProbeId("fault.live-lock"), run=run))

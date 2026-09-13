"""Inspect, corrupt or verify the rescue of a B-only initramfs in the disposable guest.

This is `guest/initramfs-fixture.py` step for step: the inspection binds both boot entries
to their deployments and fingerprints every protected input into a plan; the injection
takes that plan back by digest, lays a marked copy of B's initramfs beside the boot tree,
points B's entry at it and proves nothing else moved; the rescue check reads which entry A
boots after recovery. Every change happens in the caller's private mount namespace.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, bootentries, deployments, guestguard, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, quantities, refusals, safepaths
from apex.provisioning.fixtures import initramfs_fixture, recovery_fixture

INSPECT = "inspect"
INJECT = "inject"
RESCUE = "verify-rescue"
ACTIONS = (INSPECT, INJECT, RESCUE)
FINALISERS = ("ostree-finalize-staged", "greenboot-set-rollback-trigger")
INACTIVE = "inactive"
NEXT_DEPLOYMENT = "greenboot_next_deployment_id"
FALLBACK = "fallback"
BOOT_COUNTER = "boot_counter"
GRUB_ENVIRONMENT = commands.Argv.of("grub2-editenv", "-", "list")
ENFORCEMENT = commands.Argv.of("getenforce")
ENFORCING = "Enforcing"
REMOUNT = commands.Argv.of("mount", "-o", "remount,rw", initramfs_fixture.BOOT_DIRECTORY)
FAULT_NAME = "bad.img"
TEMPORARY_PREFIX = ".apex-initramfs-"
RUN_ID = re.compile(r"[a-f0-9]{32}")
PRIVATE_DIRECTORY = quantities.FileMode(0o700)
PRIVATE_FILE = quantities.FileMode(0o600)
SCOPE = "B-only fault injection, not recovery acceptance"
PASS = "PASS"
BLOCKED = "BLOCKED"


def _argument(arguments: Mapping[str, encoding.JsonValue], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject=f"{name} must be a string"
        )
    return value


def _require_guest(ports: agentports.AgentPorts) -> None:
    guestguard.require_installed(ports)
    if deployments.output(ports, ENFORCEMENT).strip() != ENFORCING:
        raise deployments.unexpected("expected an enforcing installed guest")
    deployments.require_private_mounts()


def _digests(good: str, bad: str) -> None:
    if good == bad:
        raise deployments.unexpected("two distinct fixture digests are required")
    identifiers.ImageId.parse(good)
    identifiers.ImageId.parse(bad)


def _targets(status: deployments.Status) -> dict[str, safepaths.SafePath]:
    if status.booted is None or status.rollback is None:
        raise deployments.unexpected("both deployments are required")
    return {"a": status.booted.path(), "b": status.rollback.path()}


def _armed_state(ports: agentports.AgentPorts, good: str, bad: str) -> deployments.Status:
    status = deployments.read(ports)
    rollback = status.rollback.image if status.rollback is not None else None
    if (
        status.booted is None or status.booted.image != good or status.staged is not None
        or rollback != bad or not status.rollback_queued
    ):
        raise deployments.unexpected("finalize signed B through its services while A is booted")
    for unit in FINALISERS:
        state = deployments.output(
            ports, commands.Argv.of("systemctl", "show", unit, "-p", "ActiveState", "--value")
        )
        if state.strip() != INACTIVE:
            raise deployments.unexpected("finalization services must complete before injection")
    deployments.require_components(ports, recovery_fixture.EXPECTED_COMPONENTS)
    return status


def _environment(ports: agentports.AgentPorts, bad: str) -> dict[str, str]:
    held = deployments.environment(deployments.output(ports, GRUB_ENVIRONMENT))
    if held.get(NEXT_DEPLOYMENT) != bad or held.get(FALLBACK) != "1" or BOOT_COUNTER in held:
        raise deployments.unexpected("expected the naturally armed first-update GRUB state")
    return held


def inspect(ports: agentports.AgentPorts, good: str, bad: str) -> encoding.Document:
    """The plan an injection is reviewed against: state, entries and protected inputs."""
    _digests(good, bad)
    status = _armed_state(ports, good, bad)
    held = _environment(ports, bad)
    bound = bootentries.bind(ports, _targets(status))
    if bound["b"].entry.version != "2" or bound["a"].entry.version != "1":
        raise deployments.unexpected("B must be the default entry, with A the previous one")
    boot_id = ports.files.read_bytes(
        safepaths.SafePath(Path(defaults.BOOT_ID)), limit=defaults.DOCUMENT_LIMIT.value
    )
    return {
        "bootc": status.document, "grubenv": dict(held),
        "entries": {version: one.document() for version, one in bound.items()},
        "protected": bootentries.protected(ports, bound), "boot_id": boot_id.decode().strip(),
    }


def _entries(plan: encoding.Document) -> dict[str, bootentries.Bound]:
    held = plan.get("entries")
    if not isinstance(held, dict):
        raise deployments.unexpected("the plan names no entries")
    found: dict[str, bootentries.Bound] = {}
    for version, item in held.items():
        files_held = item.get("files") if isinstance(item, dict) else None
        if not isinstance(item, dict) or not isinstance(files_held, dict):
            raise deployments.unexpected("the plan's entries are malformed")
        text = str(item.get("text"))
        found[version] = bootentries.Bound(
            version=version, path=str(item.get("path")), text=text,
            entry=initramfs_fixture.parse_entry(text), deployment=str(item.get("deployment")),
            marker={}, boot_files={str(k): str(v) for k, v in files_held.items()},
        )
    return found


def _protected(plan: encoding.Document) -> dict[str, encoding.JsonValue]:
    held = plan.get("protected")
    if not isinstance(held, dict):
        raise deployments.unexpected("the plan names no protected inputs")
    return dict(held)


def _fault_file(
    ports: agentports.AgentPorts, source: safepaths.SafePath, run_id: str
) -> safepaths.SafePath:
    """The marked copy of B's first bytes, laid down beside the boot tree with B's label."""
    directory = safepaths.SafePath(Path(initramfs_fixture.FAULT_DIRECTORY) / run_id)
    if ports.files.exists(directory):
        raise deployments.unexpected(f"{directory}: the fault directory already exists")
    ports.files.make_directory(directory, mode=PRIVATE_DIRECTORY)
    head = ports.files.read_bytes(source, limit=initramfs_fixture.MINIMUM_INITRAMFS_BYTES)
    target = directory / FAULT_NAME
    ports.files.write_atomic(target, initramfs_fixture.corrupted_head(head), mode=PRIVATE_FILE)
    deployments.output(ports, commands.Argv.of("chcon", f"--reference={source}", str(target)))
    return target


def _swap_entry(
    ports: agentports.AgentPorts,
    target: safepaths.SafePath,
    after: str,
    expected: encoding.JsonValue,
    run_id: str,
) -> None:
    """Write the changed entry beside the old one, label it, and replace atomically."""
    temporary = safepaths.SafePath(target.path.parent / f"{TEMPORARY_PREFIX}{run_id}")
    ports.files.write_atomic(temporary, after.encode(), mode=ports.files.mode_of(target))
    deployments.output(ports, commands.Argv.of("chcon", f"--reference={target}", str(temporary)))
    if bootentries.fingerprint(ports, target) != expected:
        raise deployments.unexpected("BLS entry changed during preparation")
    ports.files.replace(temporary, target)
    deployments.output(ports, commands.Argv.of("sync", "-f", initramfs_fixture.BOOT_DIRECTORY))


def inject(
    ports: agentports.AgentPorts, plan: encoding.Document, run_id: str, expected: str
) -> encoding.Document:
    if not RUN_ID.fullmatch(run_id) or initramfs_fixture.plan_digest(plan).hex != expected:
        raise deployments.unexpected("reviewed plan is missing or changed")
    entries = _entries(plan)
    protected = _protected(plan)
    b = entries["b"]
    source = safepaths.SafePath(Path(b.boot_files["initrd"]))
    if ports.files.identity(source).size < initramfs_fixture.MINIMUM_INITRAMFS_BYTES:
        raise deployments.unexpected("unexpected source initramfs size")
    bad_reference = f"{Path(initramfs_fixture.FAULT_DIRECTORY).name}/{run_id}/{FAULT_NAME}"
    after = initramfs_fixture.modified_entry(b.text, f"/{bad_reference}")
    bootentries.unchanged(ports, protected, except_for="")
    initramfs_fixture.require_isolated(
        entries["a"].entry, b.entry,
        a_initrd=entries["a"].boot_files["initrd"], b_initrd=b.boot_files["initrd"],
    )
    proof = safepaths.SafePath(Path(initramfs_fixture.TEST_DIRECTORY) / run_id)
    if ports.files.exists(proof):
        raise deployments.unexpected(f"{proof}: the proof directory already exists")
    ports.files.make_directory(proof, mode=PRIVATE_DIRECTORY)
    ports.files.write_atomic(proof / "before.json", encoding.canonical(plan), mode=PRIVATE_FILE)
    ports.files.write_atomic(proof / "bls-before.conf", b.text.encode(), mode=PRIVATE_FILE)
    deployments.output(ports, REMOUNT)
    bad_file = _fault_file(ports, source, run_id)
    target = safepaths.SafePath(Path(b.path))
    _swap_entry(ports, target, after, protected[str(target)], run_id)
    bootentries.unchanged(ports, protected, except_for=str(target))
    result: encoding.Document = {
        "status": PASS, "scope": SCOPE, "plan_sha256": expected, "directory": str(proof),
        "bad_file": str(bad_file), "bad_file_identity": bootentries.fingerprint(ports, bad_file),
        "changed_bls": str(target), "bls_after": after,
        "bls_after_sha256": ports.digests.file(target).hex, "other_boot_inputs_unchanged": True,
    }
    ports.files.write_atomic(proof / "result.json", encoding.canonical(result), mode=PRIVATE_FILE)
    deployments.output(ports, commands.Argv.of("sync", "-f", str(proof)))
    return result


def rescue(ports: agentports.AgentPorts, good: str, bad: str) -> encoding.Document:
    """Which entry boots A after recovery: its own initramfs, or the fault's."""
    status = deployments.read(ports)
    rollback = status.rollback.image if status.rollback is not None else None
    if status.booted is None or status.booted.image != good or status.staged or rollback != bad:
        raise deployments.unexpected("expected rescued A and retained B")
    bound = bootentries.bind(ports, _targets(status), allow_fault=True)
    binding = initramfs_fixture.rescue_binding({v: one.entry for v, one in bound.items()})
    return {
        "status": PASS if binding.safe_to_reboot_a else BLOCKED,
        "safe_to_reboot_a": binding.safe_to_reboot_a,
        "scope": initramfs_fixture.SCOPE,
        "reason": binding.reason,
        "entries": {v: one.document() for v, one in bound.items()},
    }


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    action = _argument(arguments, "action")
    if action not in ACTIONS:
        raise errors.Refusal(refusals.RefusalReason.REQUEST_MALFORMED, subject=f"action {action}")
    good, bad = _argument(arguments, "good"), _argument(arguments, "bad")
    _require_guest(ports)
    if action == RESCUE:
        return rescue(ports, good, bad)
    plan = inspect(ports, good, bad)
    if action == INSPECT:
        return {"plan": plan, "sha256": initramfs_fixture.plan_digest(plan).hex}
    return inject(ports, plan, _argument(arguments, "run_id"), _argument(arguments, "plan_sha256"))


units.declare(units.Unit(id=identifiers.ProbeId("fixture.initramfs"), run=run))

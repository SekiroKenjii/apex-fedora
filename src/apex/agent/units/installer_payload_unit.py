"""Damage the bundled payload in one named way and prove the guard refuses it before Anaconda.

This is `guest/test-installer-fault.py`: the same guards over the offline installer guest,
the same six mutations each with a byte-for-byte backup, the same run of the production
entry point, and the same reading of what it left behind. Every refusal the older script
made before the mutation is a refusal here; what the entry point did is a report.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, guestguard, units
from apex.config import defaults
from apex.kernel import commands, encoding, errors, identifiers, quantities, refusals, safepaths
from apex.ports import files as files_port
from apex.trust import preflight

PASS = "PASS"
FAIL = "FAIL"
SCOPE = "offline installer entry point in a disposable VM"
CASE_ARGUMENT = "case"
KEY_ARGUMENT = "wrong_public_key"
CASES: Mapping[str, str] = {
    "missing-signature": "signature",
    "altered-signature": "signature",
    "wrong-key": "signature",
    "changed-manifest": "Bundled manifest digest changed",
    "corrupt-blob": "Bundled blob checksum mismatch",
    "unexpected-source": "Unexpected payload source",
}
PAYLOAD = safepaths.SafePath(Path(defaults.INSTALLER_PAYLOAD))
TRUST = safepaths.SafePath(Path(defaults.INSTALLER_TRUST))
MARKER = safepaths.SafePath(Path(defaults.INSTALLER_MARKER))
RECORD = safepaths.SafePath(Path(defaults.INSTALLER_PREFLIGHT_RECORD))
FAULT_DIRECTORY = safepaths.SafePath(Path(defaults.INSTALLER_FAULT_DIRECTORY))
POLICY = safepaths.SafePath(Path(defaults.CONTAINER_POLICY))
UPSTREAM_LOG = safepaths.SafePath(Path(defaults.ANACONDA_LOG))
CMDLINE = safepaths.SafePath(Path("/proc/cmdline"))
INTERFACES = safepaths.SafePath(Path("/sys/class/net"))
PROCESSES = safepaths.SafePath(Path("/proc"))
DIAGNOSTIC_TARGET = "systemd.unit=multi-user.target"
ENFORCING = "Enforcing"
LOOPBACK = "lo"
ANACONDA = "anaconda"
KEY_HEADER = "-----BEGIN PUBLIC KEY-----\n"
CONFIG_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
DISK_NAME = re.compile(r"vd[a-z]")
SENTINEL_SERIAL = "apex-other-1"
SENTINEL_BYTES = 4 * 1024**3
TARGET_BYTES = 48 * 1024**3
UNTRUSTED_PREFIX = "localhost/apex-untrusted@"
TAMPERED_ANNOTATION = "apex.test.tampered"
SIGNATURE_PREFIX = "signature-"
DIRECTORY_MODE = quantities.FileMode(0o700)
ENTRY_POINT = commands.Argv.of("/usr/bin/anaconda", "--text")
ENFORCEMENT = commands.Argv.of("getenforce")
ANACONDA_STATE = commands.Argv.of(
    "systemctl",
    "show",
    "anaconda.service",
    "-p",
    "ActiveState",
    "-p",
    "ExecMainStartTimestampMonotonic",
)
DISKS = commands.Argv.of("lsblk", "-bJ", "-o", "NAME,SIZE,TYPE,SERIAL,MOUNTPOINTS")
NEVER_STARTED = frozenset({"ActiveState=inactive", "ExecMainStartTimestampMonotonic=0"})


def _output(ports: agentports.AgentPorts, argv: commands.Argv) -> str:
    completed = ports.processes.run(
        argv, deadline=defaults.INSTALLER_QUERY_DEADLINE, limit=commands.OutputLimit.default()
    )
    if not completed.succeeded:
        raise guestguard.refuse(f"{argv.arguments[0]} exited with {completed.exit_code}")
    return completed.stdout.decode(errors="replace").strip()


def _read(ports: agentports.AgentPorts, path: safepaths.SafePath) -> bytes:
    return ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)


def _unexpected(detail: str) -> errors.Refusal:
    return errors.Refusal(
        refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED,
        subject=detail,
        remedy="the fault is injected only into the disposable installer fixture it expects",
    )


def _malformed(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.REQUEST_MALFORMED, subject=detail)


def _anaconda_running(ports: agentports.AgentPorts) -> bool:
    for entry in ports.files.list_directory(PROCESSES):
        if not entry.relative.isdigit():
            continue
        try:
            name = ports.files.read_bytes(PROCESSES / entry.relative / "comm", limit=64)
        except errors.PortFailure:
            continue
        if name.decode(errors="replace").strip() == ANACONDA:
            return True
    return False


def _unchanged_start_state(ports: agentports.AgentPorts) -> str:
    """Anaconda must never have started during this boot; otherwise the fault is a diagnostic."""
    if ports.files.exists(RECORD) or ports.files.exists(UPSTREAM_LOG):
        raise _unexpected("this boot has already entered the installer")
    properties = _output(ports, ANACONDA_STATE)
    if set(properties.splitlines()) != NEVER_STARTED:
        raise _unexpected("Anaconda must never have started during this boot")
    if _anaconda_running(ports):
        raise _unexpected("Anaconda is already running")
    return properties


def _disks(ports: agentports.AgentPorts) -> encoding.JsonValue:
    listing = encoding.parse_object(_output(ports, DISKS).encode()).get("blockdevices")
    devices = listing if isinstance(listing, list) else []
    physical = [
        item
        for item in devices
        if isinstance(item, dict)
        and item.get("type") == "disk"
        and not str(item.get("name", "")).startswith("zram")
    ]
    if len(physical) != 2 or sorted(int(str(item.get("size", 0))) for item in physical) != [
        SENTINEL_BYTES,
        TARGET_BYTES,
    ]:
        raise _unexpected("expected only the disposable 48 GiB target and 4 GiB sentinel disk")
    for disk in physical:
        if not DISK_NAME.fullmatch(str(disk.get("name", ""))):
            raise _unexpected("expected virtio test disks only")
        if int(str(disk.get("size"))) == SENTINEL_BYTES and disk.get("serial") != SENTINEL_SERIAL:
            raise _unexpected("unexpected sentinel disk identity")
        children = disk.get("children", [])
        nodes = [disk, *(children if isinstance(children, list) else [])]
        if any(_mounted(node) for node in nodes):
            raise _unexpected("test disks must be unmounted before fault injection")
    return listing


def _mounted(node: object) -> bool:
    if not isinstance(node, dict):
        return False
    mountpoints = node.get("mountpoints", [])
    return isinstance(mountpoints, list) and any(mountpoints)


def guard(ports: agentports.AgentPorts, case: str) -> encoding.Document:
    if case not in CASES:
        raise _malformed(f"{CASE_ARGUMENT} must be one of {', '.join(CASES)}")
    guestguard.require_root()
    guestguard.require_virtual(ports)
    cmdline = _read(ports, CMDLINE).decode(errors="replace").strip()
    if DIAGNOSTIC_TARGET not in cmdline.split():
        raise guestguard.refuse("boot the installer into its diagnostic multi-user target first")
    if _output(ports, ENFORCEMENT) != ENFORCING:
        raise guestguard.refuse("SELinux must remain enforcing")
    interfaces = {entry.relative for entry in ports.files.list_directory(INTERFACES)}
    if interfaces != {LOOPBACK}:
        raise guestguard.refuse("the negative installer test must have no network interface")
    for path in (PAYLOAD, TRUST, MARKER):
        if not ports.files.exists(path) or ports.files.resolve(path) != path:
            raise guestguard.refuse("expected the Apex live installer payload without symlinks")
    disks = _disks(ports)
    return {
        "cmdline": cmdline,
        "anaconda": _unchanged_start_state(ports),
        "disks": disks,
        "selinux": ENFORCING,
        "network": "loopback-only",
    }


def _target(ports: agentports.AgentPorts, case: str) -> safepaths.SafePath:
    manifest = encoding.parse_object(_read(ports, PAYLOAD / "manifest.json"))
    config = manifest.get("config")
    digest = config.get("digest", "") if isinstance(config, dict) else ""
    if not isinstance(digest, str) or not CONFIG_DIGEST.fullmatch(digest):
        raise _unexpected("expected the frozen config blob digest before injecting a fault")
    return {
        "missing-signature": PAYLOAD / "signature-1",
        "altered-signature": PAYLOAD / "signature-1",
        "wrong-key": TRUST / "payload.pub",
        "changed-manifest": PAYLOAD / "manifest.json",
        "corrupt-blob": PAYLOAD / digest.removeprefix("sha256:"),
        "unexpected-source": TRUST / "payload.json",
    }[case]


def _write_back(ports: agentports.AgentPorts, target: safepaths.SafePath, payload: bytes) -> None:
    ports.files.write_atomic(target, payload, mode=ports.files.mode_of(target))


def _rekey(
    ports: agentports.AgentPorts, target: safepaths.SafePath, original: bytes, key: str
) -> None:
    """A consistent contract under a different key, so the real verifier is what refuses."""
    if not key.startswith(KEY_HEADER) or key.encode() == original:
        raise _malformed(f"{KEY_ARGUMENT} must be a different valid public verification key")
    _write_back(ports, target, key.encode())
    metadata_path = TRUST / "payload.json"
    metadata = encoding.parse_object(_read(ports, metadata_path))
    metadata["public_key_sha256"] = hashlib.sha256(key.encode()).hexdigest()
    _write_back(ports, metadata_path, json.dumps(metadata).encode())
    policy = preflight.load().signature_policy(metadata, key.encode(), payload=PAYLOAD.path)
    _write_back(ports, POLICY, json.dumps(policy).encode())


def _apply(
    ports: agentports.AgentPorts, case: str, target: safepaths.SafePath, original: bytes, key: str
) -> None:
    if case == "missing-signature":
        names = sorted(
            entry.relative
            for entry in ports.files.list_directory(PAYLOAD)
            if entry.relative.startswith(SIGNATURE_PREFIX)
        )
        if names != ["signature-1"]:
            raise _unexpected("review an installer with multiple signatures before testing")
        ports.files.remove(target)
    elif case in {"altered-signature", "corrupt-blob"}:
        if not original:
            raise _unexpected("cannot mutate an empty fixture")
        _write_back(ports, target, original[:-1] + bytes([original[-1] ^ 1]))
    elif case == "changed-manifest":
        _write_back(ports, target, original + b"\n")
    elif case == "unexpected-source":
        value = encoding.parse_object(original)
        value["reference"] = f"{UNTRUSTED_PREFIX}{value.get('digest', '')}"
        _write_back(ports, target, json.dumps(value).encode())
    else:
        _rekey(ports, target, original, key)


def mutate(ports: agentports.AgentPorts, case: str, key: str) -> encoding.Document:
    """One mutation per boot, with the original bytes kept beside the fault before any change."""
    if ports.files.exists(FAULT_DIRECTORY):
        raise _unexpected("one mutation per boot; an earlier fault's evidence is kept")
    ports.files.make_directory(FAULT_DIRECTORY, mode=DIRECTORY_MODE)
    target = _target(ports, case)
    if ports.files.resolve(target) != target or (
        ports.files.inspect(target).kind is not files_port.EntryKind.REGULAR
    ):
        raise _unexpected("fault target must be a regular file without symlinks")
    original = _read(ports, target)
    ports.files.write_atomic(FAULT_DIRECTORY / "original", original, mode=defaults.RECORD_MODE)
    _apply(ports, case, target, original, key)
    after = hashlib.sha256(_read(ports, target)).hexdigest() if ports.files.exists(target) else None
    return {
        "target": str(target),
        "before_sha256": hashlib.sha256(original).hexdigest(),
        "after_sha256": after,
    }


def _judged(report: Mapping[str, encoding.JsonValue], case: str) -> bool:
    record = report.get("preflight")
    error = str(record.get("error", "")) if isinstance(record, dict) else ""
    return (
        report.get("returncode") == 1
        and isinstance(record, dict)
        and record.get("status") == FAIL
        and re.search(CASES[case], error, re.IGNORECASE) is not None
        and report.get("upstream_log_created") is False
        and report.get("selinux_after") == ENFORCING
    )


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    case = str(arguments.get(CASE_ARGUMENT, ""))
    key = arguments.get(KEY_ARGUMENT, "")
    if not isinstance(key, str):
        raise _malformed(f"{KEY_ARGUMENT} must be text")
    report: dict[str, encoding.JsonValue] = {"case": case, "status": FAIL, "scope": SCOPE}
    report["before"] = guard(ports, case)
    report["trusted_metadata"] = encoding.parse_object(_read(ports, TRUST / "payload.json"))
    report["mutation"] = mutate(ports, case, key)
    try:
        completed = ports.processes.run(
            ENTRY_POINT, deadline=defaults.ANACONDA_DEADLINE, limit=commands.OutputLimit.default()
        )
    except errors.PortFailure as failure:
        report["failure"] = failure.cause
        return report
    report["returncode"] = completed.exit_code
    report["stdout"] = completed.stdout.decode(errors="replace")
    report["stderr"] = completed.stderr.decode(errors="replace")
    report["preflight"] = (
        encoding.parse_object(_read(ports, RECORD)) if ports.files.exists(RECORD) else None
    )
    report["upstream_log_created"] = ports.files.exists(UPSTREAM_LOG)
    report["selinux_after"] = _output(ports, ENFORCEMENT)
    if _judged(report, case):
        report["status"] = PASS
    return report


units.declare(units.Unit(id=identifiers.ProbeId("fault.installer-payload"), run=run))

"""File-backed multiboot media, prepared in the builder from reviewed inputs only.

The steps are the older `ventoy-fixture.py` in order: the reviewed request, the inputs
checked against it, the packages, the upstream archive unpacked and its version read back, a
sparse image attached as the loop device that must belong to it, the installer run against
that device alone, the table and the version checked, the two ISOs copied and hashed again,
and the QCOW2 output. No physical medium is ever named.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path

from apex.agent import agentports, builder, units
from apex.config import defaults
from apex.kernel import (
    commands,
    encoding,
    errors,
    identifiers,
    quantities,
    refusals,
    safepaths,
    timing,
)
from apex.provisioning import backingchain
from apex.provisioning.fixtures import ventoy_fixture

DIRECTORY_MODE = quantities.FileMode(0o700)
OUTPUT_MODE = quantities.FileMode(0o755)
LOOP = re.compile(r"/dev/loop[0-9]+")
BLOCK_CLASS = "/sys/class/block"
ACCEPT = b"y\ny\n"


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    builder.require_isolated(ports)
    work = _work(arguments)
    request = ventoy_fixture.parse_request(
        _object(_read(ports, work / ventoy_fixture.REQUEST_NAME))
    )
    _verify_inputs(ports, work, request)
    if ports.files.free_space(work) < ventoy_fixture.REQUIRED_FREE.as_bytes():
        raise _unexpected(f"need {ventoy_fixture.REQUIRED_FREE.value} GiB free inside builder")
    _run(
        ports,
        "dnf5",
        "-y",
        "install",
        *ventoy_fixture.PACKAGES,
        deadline=defaults.PACKAGE_INSTALL_DEADLINE,
    )
    upstream = _unpack(ports, work, request)
    raw = work / ventoy_fixture.RAW_IMAGE
    ports.files.reserve(raw, size=ventoy_fixture.MEDIA_SIZE.as_bytes(), mode=defaults.RECORD_MODE)
    loop = _attach(ports, raw)
    mount = work / ventoy_fixture.MOUNT_POINT
    ports.files.make_directory(mount, mode=DIRECTORY_MODE)
    mounted = False
    try:
        _install(ports, upstream, loop, raw)
        partition = f"{loop}p1"
        table = _table(ports, loop, partition)
        info = _installed_version(ports, upstream, loop, request)
        _run(
            ports,
            "mount",
            "-t",
            ventoy_fixture.FILESYSTEM,
            "-o",
            ventoy_fixture.MOUNT_OPTIONS,
            partition,
            str(mount),
        )
        mounted = True
        _copy_isos(ports, work, mount, request)
        os.sync()
        _run(ports, "umount", str(mount))
        mounted = False
        _run(ports, "fsck.exfat", "-n", partition)
    finally:
        if mounted:
            _run(ports, "umount", str(mount))
        _verify_loop(ports, loop, raw)
        _run(ports, "losetup", "--detach", loop)
    return _finish(ports, work, raw, request, table, info)


def _finish(
    ports: agentports.AgentPorts,
    work: safepaths.SafePath,
    raw: safepaths.SafePath,
    request: ventoy_fixture.VentoyRequest,
    table: encoding.JsonValue,
    info: str,
) -> encoding.Document:
    output = work / "output"
    ports.files.make_directory(output, mode=OUTPUT_MODE)
    image = output / ventoy_fixture.IMAGE
    _run(
        ports,
        backingchain.QEMU_IMG,
        "convert",
        "-f",
        "raw",
        "-O",
        "qcow2",
        str(raw),
        str(image),
        deadline=defaults.IMAGE_TOOL_DEADLINE,
    )
    _run(
        ports,
        backingchain.QEMU_IMG,
        "check",
        "-f",
        "qcow2",
        str(image),
        deadline=defaults.IMAGE_TOOL_DEADLINE,
    )
    tools = _run(ports, "rpm", "-q", *ventoy_fixture.PACKAGES).stdout.decode(errors="replace")
    report: encoding.Document = {
        "status": "PASS",
        "request": {
            "files": {name: d.hex for name, d in request.files.items()},
            "ventoy_version": request.version,
        },
        "partition_table": table,
        "ventoy_info": info,
        "image_sha256": ports.digests.file(image).hex,
        "virtual_size": ventoy_fixture.MEDIA_SIZE.bytes,
        "reserved_unformatted_mib": ventoy_fixture.RESERVED.value,
        "physical_media_accessed": False,
        "boot_acceptance": "NOT TESTED",
        "secure_boot_acceptance": "NOT TESTED",
        "retained_work": str(work),
        "tools": tools,
    }
    ports.files.write_atomic(
        output / ventoy_fixture.REPORT_NAME,
        encoding.canonical(report) + b"\n",
        mode=defaults.RECORD_MODE,
    )
    return report


def _verify_inputs(
    ports: agentports.AgentPorts, work: safepaths.SafePath, request: ventoy_fixture.VentoyRequest
) -> None:
    for name, expected in request.files.items():
        candidate = work / name
        if not ports.files.exists(candidate) or ports.digests.file(candidate) != expected:
            raise errors.Refusal(
                refusals.RefusalReason.FIXTURE_REQUEST_MALFORMED,
                subject=f"input checksum mismatch: {name}",
            )


def _unpack(
    ports: agentports.AgentPorts, work: safepaths.SafePath, request: ventoy_fixture.VentoyRequest
) -> safepaths.SafePath:
    extracted = work / ventoy_fixture.UPSTREAM
    ports.files.make_directory(extracted, mode=DIRECTORY_MODE)
    ports.archives.extract(work / ventoy_fixture.ARCHIVE, into=extracted)
    upstream = extracted / f"ventoy-{request.version}"
    marker = upstream / "ventoy" / "version"
    if not ports.files.exists(marker):
        raise _unexpected("the archive does not hold the reviewed version")
    version = _read(ports, marker).decode(errors="replace").strip()
    if version != request.version:
        raise _unexpected("archive version differs from the reviewed request")
    return upstream


def _attach(ports: agentports.AgentPorts, raw: safepaths.SafePath) -> str:
    attached = _run(ports, "losetup", "--find", "--show", "--partscan", str(raw))
    loop = attached.stdout.decode().strip()
    _verify_loop(ports, loop, raw)
    return loop


def _verify_loop(ports: agentports.AgentPorts, loop: str, raw: safepaths.SafePath) -> None:
    node = safepaths.SafePath(Path(loop))
    backing = safepaths.SafePath(Path(BLOCK_CLASS) / Path(loop).name / "loop" / "backing_file")
    if not LOOP.fullmatch(loop) or not ports.files.exists(node):
        raise _unexpected("expected a newly allocated loop device")
    if Path(_read(ports, backing).decode().strip()) != raw.path:
        raise _unexpected("loop device does not belong to this new file")


def _install(
    ports: agentports.AgentPorts, upstream: safepaths.SafePath, loop: str, raw: safepaths.SafePath
) -> None:
    # No arbitrary device operand: only the loop returned for the new raw file.
    _run(
        ports,
        "sh",
        ventoy_fixture.INSTALLER,
        "-i",
        "-r",
        str(ventoy_fixture.RESERVED.value),
        loop,
        cwd=upstream,
        stdin=ACCEPT,
        deadline=defaults.IMAGE_TOOL_DEADLINE,
    )
    _verify_loop(ports, loop, raw)
    _run(ports, "udevadm", "settle", "--timeout=30")


def _table(ports: agentports.AgentPorts, loop: str, partition: str) -> encoding.JsonValue:
    if not ports.files.exists(safepaths.SafePath(Path(partition))):
        raise _unexpected("Ventoy data partition is missing")
    table = _object(_run(ports, "sfdisk", "--json", loop).stdout)
    layout = table.get("partitiontable")
    if not isinstance(layout, dict) or layout.get("label") != ventoy_fixture.PARTITION_TABLE:
        raise _unexpected("unexpected Ventoy MBR layout")
    partitions = layout.get("partitions")
    if not isinstance(partitions, list) or len(partitions) != ventoy_fixture.PARTITIONS:
        raise _unexpected("unexpected Ventoy MBR layout")
    return table


def _installed_version(
    ports: agentports.AgentPorts,
    upstream: safepaths.SafePath,
    loop: str,
    request: ventoy_fixture.VentoyRequest,
) -> str:
    info = _run(ports, "sh", ventoy_fixture.INSTALLER, "-l", loop, cwd=upstream).stdout.decode(
        errors="replace"
    )
    if f"{ventoy_fixture.VERSION_LINE}{request.version}" not in info:
        raise _unexpected("installed Ventoy version does not match")
    return info


def _copy_isos(
    ports: agentports.AgentPorts,
    work: safepaths.SafePath,
    mount: safepaths.SafePath,
    request: ventoy_fixture.VentoyRequest,
) -> None:
    for name in ventoy_fixture.ISOS:
        ports.files.copy(work / name, mount / name)
        if ports.digests.file(mount / name) != request.files[name]:
            raise _unexpected("ISO checksum changed on the virtual USB")


def _run(
    ports: agentports.AgentPorts,
    *argv: str,
    stdin: bytes | None = None,
    cwd: safepaths.SafePath | None = None,
    deadline: timing.Deadline | None = None,
) -> commands.CompletedRun:
    completed = ports.processes.run(
        commands.Argv.of(*argv),
        deadline=deadline or defaults.GUEST_COMMAND_DEADLINE,
        limit=commands.OutputLimit.default(),
        stdin=stdin,
        cwd=cwd,
    )
    if not completed.succeeded:
        raise errors.PortFailure(
            port="process",
            cause=f"{argv[0]} exited with {completed.exit_code}: "
            f"{completed.stderr.decode(errors='replace').strip()}",
        )
    return completed


def _read(ports: agentports.AgentPorts, path: safepaths.SafePath) -> bytes:
    return ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)


def _work(arguments: Mapping[str, encoding.JsonValue]) -> safepaths.SafePath:
    value = arguments.get("work")
    if not isinstance(value, str) or not value.startswith("/"):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject="work must be an absolute path"
        )
    return safepaths.SafePath(Path(value))


def _object(payload: bytes) -> dict[str, encoding.JsonValue]:
    try:
        return encoding.parse_object(payload)
    except ValueError as fault:
        raise errors.Refusal(
            refusals.RefusalReason.FIXTURE_REQUEST_MALFORMED, subject=str(fault)
        ) from fault


def _unexpected(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED, subject=detail)


units.declare(units.Unit(id=identifiers.ProbeId("fixture.ventoy"), run=run))

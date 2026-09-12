"""Two disposable disks for installer tests: three foreign filesystems, and an empty target.

The steps are the older `installer-fixtures.py` in order, each through a port: the packages,
the raw image, its table, the loop device that must belong to that image, one formatted and
sentinelled partition at a time, and the two QCOW2 outputs. The report is the unit's reply and
is also left beside the outputs for the host to carry home.
"""

from __future__ import annotations

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
from apex.provisioning.fixtures import installer_fixture

DIRECTORY_MODE = quantities.FileMode(0o700)
SENTINEL_MODE = quantities.FileMode(0o644)
LOOP_PREFIX = "/dev/loop"
BLOCK_CLASS = "/sys/class/block"


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    builder.require_isolated(ports)
    work = _directory(arguments, "work")
    output = _directory(arguments, "output")
    token = str(arguments.get("token", ""))
    _run(ports, "dnf5", "-y", "install", *installer_fixture.PACKAGES,
         deadline=defaults.PACKAGE_INSTALL_DEADLINE)
    ports.files.make_directory(work, mode=DIRECTORY_MODE)
    raw = safepaths.SafePath(work.path / installer_fixture.RAW_IMAGE)
    _run(ports, "truncate", "-s", f"{installer_fixture.OTHER_SIZE.value}G", str(raw))
    _run(ports, "sfdisk", str(raw), stdin=installer_fixture.layout().encode())
    loop = _attach(ports, raw)
    mount = safepaths.SafePath(work.path / installer_fixture.MOUNT_POINT)
    ports.files.make_directory(mount, mode=DIRECTORY_MODE)
    records: list[encoding.JsonValue] = []
    try:
        for partition in installer_fixture.PARTITIONS:
            records.append(_prepare(ports, loop, partition, mount=mount, token=token))
    finally:
        _run(ports, "losetup", "--detach", loop)
    ports.files.make_directory(output, mode=DIRECTORY_MODE)
    other = safepaths.SafePath(output.path / installer_fixture.OTHER_IMAGE)
    target = safepaths.SafePath(output.path / installer_fixture.TARGET_IMAGE)
    _run(ports, backingchain.QEMU_IMG, "convert", "-f", "raw", "-O", "qcow2", str(raw), str(other),
         deadline=defaults.IMAGE_TOOL_DEADLINE)
    _run(ports, backingchain.QEMU_IMG, "create", "-f", "qcow2", str(target),
         f"{installer_fixture.TARGET_SIZE.value}G", deadline=defaults.IMAGE_TOOL_DEADLINE)
    table = _run(ports, "sfdisk", "--json", str(raw)).stdout.decode(errors="replace")
    report: encoding.Document = {
        "purpose": installer_fixture.PURPOSE,
        "bootable_existing_systems": False,
        "layout": encoding.parse_document(table.encode()),
        "partitions": records,
        "retained_work": str(work),
        "sha256": {
            installer_fixture.OTHER_IMAGE: ports.digests.file(other).hex,
            installer_fixture.TARGET_IMAGE: ports.digests.file(target).hex,
        },
    }
    ports.files.write_atomic(
        safepaths.SafePath(output.path / installer_fixture.REPORT_NAME),
        encoding.canonical(report) + b"\n",
        mode=defaults.RECORD_MODE,
    )
    return report


def _attach(ports: agentports.AgentPorts, raw: safepaths.SafePath) -> str:
    attached = _run(ports, "losetup", "--find", "--show", "--partscan", str(raw))
    loop = attached.stdout.decode().strip()
    backing = safepaths.SafePath(Path(BLOCK_CLASS) / Path(loop).name / "loop" / "backing_file")
    recorded = ports.files.read_bytes(backing, limit=defaults.DOCUMENT_LIMIT.value)
    if not loop.startswith(LOOP_PREFIX) or Path(recorded.decode().strip()) != raw.path:
        raise errors.Refusal(
            refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED,
            subject=f"{loop} does not refer to the newly created fixture file",
        )
    return loop


def _prepare(
    ports: agentports.AgentPorts,
    loop: str,
    partition: installer_fixture.Partition,
    *,
    mount: safepaths.SafePath,
    token: str,
) -> encoding.Document:
    device = f"{loop}p{partition.index}"
    node = safepaths.SafePath(Path(device))
    ports.clock.wait_until(lambda: ports.files.exists(node), defaults.PARTITION_APPEARS)
    _run(ports, *partition.format_argv(device), deadline=defaults.IMAGE_TOOL_DEADLINE)
    _run(ports, "mount", "-t", partition.filesystem, "-o", installer_fixture.MOUNT_OPTIONS,
         device, str(mount))
    try:
        sentinel = safepaths.SafePath(mount.path / partition.sentinel)
        content = f"Disposable Apex installer fixture {partition.index}: {token}\n".encode()
        digest = ports.files.write_atomic(sentinel, content, mode=SENTINEL_MODE)
    finally:
        _run(ports, "umount", str(mount))
    return {
        "partition": partition.index,
        "filesystem": partition.filesystem,
        "sentinel": partition.sentinel,
        "sentinel_sha256": digest.hex,
    }


def _run(
    ports: agentports.AgentPorts,
    *argv: str,
    stdin: bytes | None = None,
    deadline: timing.Deadline | None = None,
) -> commands.CompletedRun:
    completed = ports.processes.run(
        commands.Argv.of(*argv),
        deadline=deadline or defaults.GUEST_COMMAND_DEADLINE,
        limit=commands.OutputLimit.default(),
        stdin=stdin,
    )
    if not completed.succeeded:
        raise errors.PortFailure(
            port="process",
            cause=f"{argv[0]} exited with {completed.exit_code}: "
            f"{completed.stderr.decode(errors='replace').strip()}",
        )
    return completed


def _directory(arguments: Mapping[str, encoding.JsonValue], name: str) -> safepaths.SafePath:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.startswith("/"):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED, subject=f"{name} must be an absolute path"
        )
    return safepaths.SafePath(Path(value))


units.declare(units.Unit(id=identifiers.ProbeId("fixture.installer-disks"), run=run))

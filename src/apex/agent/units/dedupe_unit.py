"""Share identical blob extents in a completed update fixture without removing a file.

The steps are the older `dedupe-update-blobs.py` in order: the builder, the scratch filesystem
and the absence of running containers checked first; a self test that proves identical
bytes share, differing bytes are refused by the kernel, and a write to one copy does not
reach the other; then, for a completed fixture, each content-addressed blob shared between
the signed bundle and its wrong-key twin, with every manifest and signature left untouched.
"""

from __future__ import annotations

import os
import platform
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
)
from apex.model import extents
from apex.provisioning.fixtures import dedupe_fixture, update_fixture

DIRECTORY_MODE = quantities.FileMode(0o700)
PRIVATE = quantities.FileMode(0o600)
WORK_PREFIX = f"{dedupe_fixture.SCRATCH}/apex-dedupe-"
UPDATE_PREFIX = f"{dedupe_fixture.SCRATCH}/apex-update-"


def run(
    ports: agentports.AgentPorts, *, arguments: Mapping[str, encoding.JsonValue]
) -> encoding.Document:
    builder.require_isolated(ports)
    _require_scratch(ports)
    work = _work(arguments)
    ports.files.make_directory(work, mode=DIRECTORY_MODE)
    report: dict[str, encoding.JsonValue] = {
        "status": "BLOCKED",
        "files_removed": 0,
        "files": {},
        "free_before": ports.files.free_space(work).value,
    }
    try:
        report["self_test"] = _self_test(ports, work)
        fixture = arguments.get("fixture")
        if isinstance(fixture, str):
            report.update(_share_fixture(ports, identifiers.RunId.parse(fixture)))
        os.sync()
        report["free_after"] = ports.files.free_space(work).value
        report["status"] = "PASS"
    finally:
        ports.files.write_atomic(
            work / dedupe_fixture.REPORT_NAME, encoding.canonical(report) + b"\n", mode=PRIVATE
        )
    return report


def _require_scratch(ports: agentports.AgentPorts) -> None:
    if platform.machine() != dedupe_fixture.ARCHITECTURE:
        raise _refuse(f"use the isolated {dedupe_fixture.ARCHITECTURE} Fedora builder")
    completed = ports.processes.run(
        commands.Argv.of("findmnt", "-n", "-o", "FSTYPE", "-T", dedupe_fixture.SCRATCH),
        deadline=defaults.PROBE_DEADLINE,
        limit=commands.OutputLimit.default(),
    )
    if completed.stdout.decode(errors="replace").strip() != dedupe_fixture.FILESYSTEM:
        raise _refuse(f"the builder scratch filesystem must be {dedupe_fixture.FILESYSTEM}")
    try:
        running = encoding.parse_document(ports.containers.running_containers())
    except ValueError as fault:
        raise _refuse(f"container listing: {fault}") from fault
    if running:
        raise _refuse("stop build containers first")


def _self_test(ports: agentports.AgentPorts, work: safepaths.SafePath) -> encoding.Document:
    size = dedupe_fixture.SELF_TEST_SIZE.bytes
    content = os.urandom(size)
    changed = bytes([content[0] ^ 1]) + content[1:]
    source, target, wrong = (work / name for name in ("source", "target", "different"))
    for path, payload in ((source, content), (target, content), (wrong, changed)):
        ports.files.write_atomic(path, payload, mode=PRIVATE)
    shared = _share(ports, source, target)
    refused = ports.extents.share(source, wrong, extents.DedupeRange(0, extents.ALIGNMENT))
    if not refused.differed:
        raise _refuse("kernel accepted nonidentical ranges")
    ports.files.patch(target, offset=0, payload=bytes([content[0] ^ 255]))
    limit = size + 1
    if (
        ports.files.read_bytes(source, limit=limit) != content
        or ports.files.read_bytes(target, limit=limit) == content
        or ports.files.read_bytes(wrong, limit=limit) != changed
    ):
        raise _refuse("copy-on-write isolation failed")
    return {
        "identical": shared,
        "kernel_rejected_difference": True,
        "cow_write_isolation": True,
    }


def _share(
    ports: agentports.AgentPorts, source: safepaths.SafePath, target: safepaths.SafePath
) -> encoding.Document:
    """Share every aligned span of `source` into `target`, both hashed before and after."""
    expected = ports.digests.file(source)
    if ports.digests.file(target) != expected:
        raise _refuse("blob contents differ")
    size = len(ports.files.read_bytes(source, limit=defaults.DOCUMENT_LIMIT.value))
    submitted = 0
    for span in extents.spans(size):
        outcome = ports.extents.share(source, target, span)
        if not outcome.complete or outcome.bytes_deduped != span.length:
            raise _refuse(
                f"dedupe rejected or incomplete: status={outcome.status}, "
                f"bytes={outcome.bytes_deduped}/{span.length}"
            )
        submitted += outcome.bytes_deduped
    ports.digests.forget()
    if ports.digests.file(source) != expected or ports.digests.file(target) != expected:
        raise _refuse("blob identity or content changed")
    return {
        "sha256": expected.hex,
        "bytes_submitted": submitted,
        "tail_bytes_not_shared": size - extents.shareable_length(size),
        "identities_unchanged": True,
    }


def _share_fixture(
    ports: agentports.AgentPorts, fixture: identifiers.RunId
) -> dict[str, encoding.JsonValue]:
    root = safepaths.SafePath(Path(f"{UPDATE_PREFIX}{fixture}"))
    completed = update_fixture.parse_report(
        _object(ports, root / "output" / "results.json")
    )
    if completed.run != fixture:
        raise _refuse("a completed fixture is required")
    source = root / dedupe_fixture.BLOB_SOURCE
    target = root / dedupe_fixture.BLOB_TARGET
    names = _blob_names(ports, target)
    if names != _blob_names(ports, source):
        raise _refuse("unexpected blob inventory")
    preserved = {
        str(directory / name): ports.digests.file(directory / name).hex
        for directory in (source, target)
        for name in _top_level(ports, directory)
        if name not in names
    }
    manifest = ports.digests.file(source / "manifest.json")
    if identifiers.ImageId(manifest.hex) != completed.images["b"].digest:
        raise _refuse("unexpected B manifest")
    files: dict[str, encoding.JsonValue] = {}
    for name in names:
        hashed = (ports.digests.file(source / name).hex, ports.digests.file(target / name).hex)
        if hashed != (name, name):
            raise _refuse("content-addressed blob checksum mismatch")
        files[name] = _share(ports, source / name, target / name)
    ports.digests.forget()
    for path, digest in preserved.items():
        if ports.digests.file(safepaths.SafePath(Path(path))).hex != digest:
            raise _refuse("a manifest, signature or transport marker changed")
    return {
        "fixture": str(fixture),
        "original_report_sha256": ports.digests.file(root / "output" / "results.json").hex,
        "files": files,
        "preserved_sha256": preserved,
    }


def _top_level(ports: agentports.AgentPorts, directory: safepaths.SafePath) -> list[str]:
    return sorted(
        entry.relative
        for entry in ports.files.list_tree(directory)
        if "/" not in entry.relative and entry.kind is not entry.kind.DIRECTORY
    )


def _blob_names(ports: agentports.AgentPorts, directory: safepaths.SafePath) -> list[str]:
    return [
        name for name in _top_level(ports, directory) if update_fixture.BLOB_NAME.fullmatch(name)
    ]


def _object(
    ports: agentports.AgentPorts, path: safepaths.SafePath
) -> dict[str, encoding.JsonValue]:
    try:
        return encoding.parse_object(
            ports.files.read_bytes(path, limit=defaults.DOCUMENT_LIMIT.value)
        )
    except ValueError as fault:
        raise _refuse(f"{path.path.name}: {fault}") from fault


def _work(arguments: Mapping[str, encoding.JsonValue]) -> safepaths.SafePath:
    value = arguments.get("work")
    if not isinstance(value, str) or not value.startswith(WORK_PREFIX):
        raise errors.Refusal(
            refusals.RefusalReason.REQUEST_MALFORMED,
            subject=f"work must be a directory under {WORK_PREFIX}",
        )
    return safepaths.SafePath(Path(value))


def _refuse(detail: str) -> errors.Refusal:
    return errors.Refusal(refusals.RefusalReason.FIXTURE_STATE_UNEXPECTED, subject=detail)


units.declare(units.Unit(id=identifiers.ProbeId("fixture.dedupe"), run=run))

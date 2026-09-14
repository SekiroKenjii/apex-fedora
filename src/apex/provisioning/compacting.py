"""The builder's disk compacted into a compressed copy and swapped in only after every check.

The disk is converted with compression into a copy of its own under the runtime root, and
the copy is accepted only when both are well-formed QCOW2 images of one virtual size, the
copy stands alone, every guest-visible byte compares equal, no machine started and no link
of the chain changed meanwhile, and the space the swap frees brings the host over the
builder's launch threshold. A copy that compares equal and still falls short of that
threshold is kept and named, so it can be finalised later without converting again; a copy
that fails any check is kept for inspection and never swapped in. Every image tool call and
its outcome is written to the report as it happens, and the swap is one atomic rename.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from apex.config import defaults, loader
from apex.kernel import commands, encoding, errors, identifiers, refusals, safepaths
from apex.ports import locking, portset
from apex.provisioning import backingchain, compactledger, launching

PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
NOT_PERFORMED = "NOT PERFORMED"
PENDING = "VALIDATED, PENDING ATOMIC REPLACE"
COMPLETE = "COMPLETE"
SHORT_OF_SPACE = "Validated copy does not save enough space; original retained"
INFO = commands.Argv.of(backingchain.QEMU_IMG, "info", "--output=json")
CHECK = commands.Argv.of(backingchain.QEMU_IMG, "check", "--output=json")
COMPARE = commands.Argv.of(
    backingchain.QEMU_IMG, "compare", "-f", backingchain.QCOW2, "-F", backingchain.QCOW2
)
CONVERT = commands.Argv.of(
    backingchain.QEMU_IMG,
    "convert",
    "-f",
    backingchain.QCOW2,
    "-O",
    backingchain.QCOW2,
    "-c",
    "-o",
    f"compression_type={defaults.COMPRESSION_TYPE}",
    "-m",
    defaults.CONVERT_THREADS,
)
Identities = dict[str, dict[str, int]]


def _information(document: bytes) -> list[dict[str, encoding.JsonValue]]:
    loaded = encoding.parse_document(document)
    items = loaded if isinstance(loaded, list) else [loaded]
    return [dict(item) for item in items if isinstance(item, Mapping)]


def _require_plain(
    ledger: compactledger.Ledger, chain: list[dict[str, encoding.JsonValue]]
) -> None:
    """A QCOW2 chain with nothing a compressed copy would lose: no snapshot, bitmap or fault."""
    if not chain or chain[0].get("format") != backingchain.QCOW2:
        raise ledger.refuse(
            refusals.RefusalReason.COMPACTION_INPUT_UNSAFE, "expected a QCOW2 builder"
        )
    for item in chain:
        specific = item.get("format-specific")
        extra = specific.get("data", {}) if isinstance(specific, Mapping) else {}
        marks = (item.get("snapshots"), item.get("dirty-flag"))
        held = extra if isinstance(extra, Mapping) else {}
        if any(marks) or held.get("bitmaps") or held.get("corrupt"):
            raise ledger.refuse(
                refusals.RefusalReason.COMPACTION_INPUT_UNSAFE,
                "preserve snapshots and bitmaps or repair corruption before compaction",
            )


def _identities(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    chain: list[dict[str, encoding.JsonValue]],
) -> tuple[Identities, list[safepaths.SafePath]]:
    paths = [
        safepaths.SafePath.regular_file(Path(str(item["filename"])), within=root) for item in chain
    ]
    return {str(path): ports.files.identity(path).document() for path in paths}, paths


def _free(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> int:
    return ports.files.free_space(safepaths.SafePath(root.path)).value


def _projected(
    ports: portset.HostPorts,
    settings: loader.Settings,
    root: safepaths.RuntimeRoot,
    source: safepaths.SafePath,
    ledger: compactledger.Ledger,
) -> int:
    projected = _free(ports, root) + ports.files.identity(source).allocated
    if projected < settings.builder.minimum_free.bytes:
        raise ledger.refuse(refusals.RefusalReason.COMPACTION_SPACE_INSUFFICIENT, SHORT_OF_SPACE)
    return projected


def _require_unchanged(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    ledger: compactledger.Ledger,
    identities: Identities,
    paths: list[safepaths.SafePath],
) -> None:
    current = {str(path): ports.files.identity(path).document() for path in paths}
    if launching.current(ports, root=root) is not None or current != identities:
        raise ledger.refuse(
            refusals.RefusalReason.COMPACTION_STATE_CHANGED,
            "a machine started or the builder chain changed during compaction",
        )


def _require_standalone(
    ledger: compactledger.Ledger, after: list[dict[str, encoding.JsonValue]], expected_size: object
) -> None:
    _require_plain(ledger, after)
    if after[0].get("backing-filename") or after[0].get("virtual-size") != expected_size:
        raise ledger.refuse(
            refusals.RefusalReason.COMPACTION_INPUT_UNSAFE,
            "the copy must stand alone with the same virtual capacity",
        )


def _digest(ports: portset.HostPorts, path: safepaths.SafePath) -> str:
    ports.digests.forget()
    return ports.digests.file(path).hex


def _swap(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    ledger: compactledger.Ledger,
    source: safepaths.SafePath,
    target: safepaths.SafePath,
) -> None:
    ledger.note(replacement=PENDING, phase="replacing validated builder file")
    ports.files.replace(target, source)
    ledger.note(replacement=COMPLETE, free_after=_free(ports, root), status=PASS, phase="complete")


def _guarded_source(ports: portset.HostPorts, root: safepaths.RuntimeRoot) -> safepaths.SafePath:
    if launching.current(ports, root=root) is not None:
        raise errors.Refusal(
            refusals.RefusalReason.MACHINE_RUNNING,
            subject="a machine is running",
            remedy="stop every machine before compacting the builder",
        )
    source = safepaths.SafePath.regular_file(root.path / defaults.BUILDER_DISK_NAME, within=root)
    if ports.files.identity(source).links != 1:
        raise errors.Refusal(
            refusals.RefusalReason.COMPACTION_INPUT_UNSAFE,
            subject="the builder must have exactly one filesystem link",
        )
    backingchain.inspect(ports, source.path, root=root)
    return source


def compact(
    ports: portset.HostPorts, settings: loader.Settings, root: safepaths.RuntimeRoot
) -> compactledger.Compacted:
    with ports.locks.acquire(launching.MACHINE, locking.AcquisitionPolicy.immediate()):
        source = _guarded_source(ports, root)
        directory = root.child(f"{defaults.COMPACTIONS_DIRECTORY}/{ports.identities.run_id()}")
        ports.files.make_directory(directory, mode=safepaths.PRIVATE_DIRECTORY_MODE)
        target = directory / defaults.COMPRESSED_DISK_NAME
        ledger = compactledger.Ledger(
            ports,
            directory / "result.json",
            {"status": FAIL, "source": str(source), "replacement": NOT_PERFORMED},
        )
        return _compact(ports, settings, root, ledger, source, target)


def _compact(
    ports: portset.HostPorts,
    settings: loader.Settings,
    root: safepaths.RuntimeRoot,
    ledger: compactledger.Ledger,
    source: safepaths.SafePath,
    target: safepaths.SafePath,
) -> compactledger.Compacted:
    ledger.note(
        version=ledger.command(commands.Argv.of(backingchain.QEMU_IMG, "--version")).decode(
            errors="replace"
        )
    )
    chain = _information(ledger.command(INFO.extended("--backing-chain", source)))
    _require_plain(ledger, chain)
    identities, paths = _identities(ports, root, chain)
    ledger.note(before={"chain": chain, "identity": identities, "free": _free(ports, root)})
    needed = ports.files.identity(source).allocated + defaults.COMPACTION_RESERVE.bytes
    if _free(ports, root) < needed:
        raise ledger.refuse(
            refusals.RefusalReason.COMPACTION_SPACE_INSUFFICIENT,
            "not enough room for a separate compressed copy and reserve",
        )
    for path in paths:
        ledger.command(CHECK.extended(path))
    ledger.note(source_sha256=_digest(ports, source))
    ledger.command(
        CONVERT.extended(source, target),
        transcript=safepaths.SafePath(ledger.path.path.parent / defaults.CONVERT_LOG_NAME),
    )
    after = _information(ledger.command(INFO.extended(target)))
    _require_standalone(ledger, after, chain[0].get("virtual-size"))
    ledger.command(CHECK.extended(target))
    ledger.command(COMPARE.extended(source, target))
    _require_unchanged(ports, root, ledger, identities, paths)
    ledger.note(after=after[0], compressed_sha256=_digest(ports, target))
    projected = _projected(ports, settings, root, source, ledger)
    ledger.note(projected_free=projected)
    _swap(ports, root, ledger, source, target)
    return compactledger.Compacted(
        report=ledger.path, status=PASS, replacement=COMPLETE, projected_free=projected
    )


def _retained(
    ports: portset.HostPorts, source: safepaths.SafePath, previous: safepaths.SafePath
) -> tuple[dict[str, encoding.JsonValue], safepaths.SafePath]:
    """The earlier report and its copy, accepted only as a fully compared copy short of space."""
    report = encoding.parse_object(
        ports.files.read_bytes(previous / "result.json", limit=defaults.DOCUMENT_LIMIT.value)
    )
    target = previous / defaults.COMPRESSED_DISK_NAME
    unfit = errors.Refusal(
        refusals.RefusalReason.COMPACTION_RETAINED_INELIGIBLE,
        subject=str(previous),
        remedy="only a fully compared copy that was short of space can be finalised",
    )
    if report.get("source") != str(source) or report.get("replacement") != NOT_PERFORMED:
        raise unfit
    if report.get("error") != SHORT_OF_SPACE:
        raise unfit
    for name in ("source_sha256", "compressed_sha256"):
        identifiers.Digest(str(report.get(name, "")))
    recorded = report.get("commands")
    compared = [
        item
        for item in (recorded if isinstance(recorded, list) else [])
        if isinstance(item, Mapping)
        and item.get("argv") == [*COMPARE, str(source), str(target)]
        and item.get("returncode") == 0
    ]
    if len(compared) != 1 or not ports.files.exists(target):
        raise unfit
    kept = ports.files.identity(target)
    if kept.links != 1 or kept.device != ports.files.identity(source).device:
        raise unfit
    return report, target


def finalise(
    ports: portset.HostPorts,
    settings: loader.Settings,
    root: safepaths.RuntimeRoot,
    compaction: identifiers.RunId,
) -> compactledger.Compacted:
    """Swap in a copy an earlier run compared in full and kept, after checking it all again."""
    with ports.locks.acquire(launching.MACHINE, locking.AcquisitionPolicy.immediate()):
        source = _guarded_source(ports, root)
        previous = root.child(f"{defaults.COMPACTIONS_DIRECTORY}/{compaction}")
        report, target = _retained(ports, source, previous)
        directory = previous / f"{defaults.FINALISE_PREFIX}{ports.identities.token()}"
        ports.files.make_directory(directory, mode=safepaths.PRIVATE_DIRECTORY_MODE)
        ledger = compactledger.Ledger(
            ports,
            directory / "result.json",
            {
                "status": BLOCKED,
                "phase": "validating retained copy",
                "source": str(source),
                "target": str(target),
                "replacement": NOT_PERFORMED,
                "previous_report_sha256": _digest(ports, previous / "result.json"),
                "previous_run": str(compaction),
            },
        )
        return _finalise(ports, settings, root, ledger, report, source, target)


def _finalise(
    ports: portset.HostPorts,
    settings: loader.Settings,
    root: safepaths.RuntimeRoot,
    ledger: compactledger.Ledger,
    report: Mapping[str, encoding.JsonValue],
    source: safepaths.SafePath,
    target: safepaths.SafePath,
) -> compactledger.Compacted:
    chain = _information(ledger.command(INFO.extended("--backing-chain", source)))
    _require_plain(ledger, chain)
    identities, paths = _identities(ports, root, chain)
    before = report.get("before")
    if not isinstance(before, Mapping) or before.get("identity") != identities:
        raise ledger.refuse(
            refusals.RefusalReason.COMPACTION_STATE_CHANGED,
            "the original builder chain changed since the compaction",
        )
    kept = ports.files.identity(target).document()
    after = _information(ledger.command(INFO.extended(target)))
    _require_standalone(ledger, after, chain[0].get("virtual-size"))
    ledger.note(phase="hashing original and retained copy")
    for name, path in (("source_sha256", source), ("compressed_sha256", target)):
        found = _digest(ports, path)
        ledger.note(**{name: found})
        if found != report.get(name):
            raise ledger.refuse(
                refusals.RefusalReason.COMPACTION_STATE_CHANGED,
                "file content changed since the compaction",
            )
    for path in (*paths, target):
        ledger.command(CHECK.extended(path))
    ledger.note(phase="comparing complete guest data")
    ledger.command(COMPARE.extended(source, target))
    _require_unchanged(ports, root, ledger, identities, paths)
    if ports.files.identity(target).document() != kept:
        raise ledger.refuse(
            refusals.RefusalReason.COMPACTION_STATE_CHANGED,
            "the retained copy changed during finalisation",
        )
    projected = _projected(ports, settings, root, source, ledger)
    ledger.note(projected_free=projected)
    _swap(ports, root, ledger, source, target)
    return compactledger.Compacted(
        report=ledger.path, status=PASS, replacement=COMPLETE, projected_free=projected
    )

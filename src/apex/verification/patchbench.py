"""A reviewed source compiled against a test harness on the host, in a directory of its own.

The source is accepted only when its digest is one the lock reviewed; the patch is the
checkout's; the work is laid out under a fresh directory beside the store and every program
runs there through the process port, under a deadline. Root is refused before the source
is read, because these checks compile and run code the operator supplied.
"""

from __future__ import annotations

import dataclasses
import os
import shlex
from collections.abc import Mapping
from pathlib import Path

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
from apex.ports import portset

ROOT_USER = 0
PLAIN = quantities.FileMode(0o644)
GIO = "gio-2.0"
CC = "cc"
PKG_CONFIG = "pkg-config"
PATCH = commands.Argv.of("patch", "--batch", "--fuzz=0")
COMPILE = commands.Argv.of(CC, "-std=c11", "-O0", "-Wall", "-Werror")


@dataclasses.dataclass(frozen=True, slots=True)
class Reviewed:
    label: str
    digest: identifiers.Digest


@dataclasses.dataclass(frozen=True, slots=True)
class Checked:
    document: encoding.Document
    proof: safepaths.SafePath


@dataclasses.dataclass(frozen=True, slots=True)
class Bench:
    directory: safepaths.SafePath
    work: safepaths.SafePath
    source: safepaths.RegularFile
    source_digest: identifiers.Digest
    source_label: str
    patch: safepaths.RegularFile
    patch_digest: identifiers.Digest
    flags: tuple[str, ...]


def require_not_root() -> None:
    if os.geteuid() == ROOT_USER:
        raise errors.Refusal(
            refusals.RefusalReason.HOST_RUNS_AS_ROOT,
            subject="these checks compile and run code the operator supplied",
            remedy="run them as your normal user",
        )


def document(ports: portset.HostPorts, path: Path) -> dict[str, encoding.JsonValue]:
    return encoding.parse_object(
        ports.files.read_bytes(safepaths.SafePath(path), limit=defaults.DOCUMENT_LIMIT.value)
    )


def text(ports: portset.HostPorts, path: Path) -> str:
    return ports.files.read_bytes(
        safepaths.SafePath(path), limit=defaults.DOCUMENT_LIMIT.value
    ).decode(errors="replace")


def reviewed_entries(entries: object) -> tuple[Reviewed, ...]:
    if not isinstance(entries, list):
        raise errors.Refusal(
            refusals.RefusalReason.LOCK_ENTRY_MALFORMED, subject="reviewed sources must be a list"
        )
    return tuple(
        Reviewed(label=str(item["label"]), digest=identifiers.Digest(str(item["sha256"])))
        for item in entries
        if isinstance(item, Mapping)
    )


def reviewed_source(
    ports: portset.HostPorts, candidate: Path, entries: tuple[Reviewed, ...]
) -> tuple[safepaths.RegularFile, identifiers.Digest, str]:
    """The source, its digest, and the lock's label for it; anything unreviewed is refused."""
    adopted = safepaths.RegularFile.adopt(candidate)
    digest = ports.digests.file(safepaths.SafePath(adopted.path))
    for item in entries:
        if item.digest == digest:
            return adopted, digest, item.label
    raise errors.Refusal(
        refusals.RefusalReason.PATCH_SOURCE_NOT_REVIEWED,
        subject=f"{candidate}: {digest.hex}",
        remedy="download the exact source the lock names; nothing is compiled from another",
    )


def open_bench(
    ports: portset.HostPorts,
    root: safepaths.RuntimeRoot,
    repository: safepaths.SourceRoot,
    *,
    directory_name: str,
    lock_path: str,
    entries_key: str,
    source: Path,
) -> Bench:
    lock = document(ports, repository.path / lock_path)
    adopted, digest, label = reviewed_source(ports, source, reviewed_entries(lock[entries_key]))
    patch = safepaths.RegularFile.adopt(repository.path / str(lock["patch"]))
    directory = root.child(f"{directory_name}/{ports.identities.token()}")
    work = directory / defaults.PATCH_WORK_DIRECTORY
    ports.files.make_directory(work, mode=safepaths.PRIVATE_DIRECTORY_MODE)
    return Bench(
        directory=directory,
        work=work,
        source=adopted,
        source_digest=digest,
        source_label=label,
        patch=patch,
        patch_digest=ports.digests.file(safepaths.SafePath(patch.path)),
        flags=tuple(shlex.split(output(ports, work, PKG_CONFIG, "--cflags", "--libs", GIO))),
    )


def run(
    ports: portset.HostPorts,
    cwd: safepaths.SafePath,
    *argv: str,
    deadline: timing.Deadline = defaults.COMPILE_DEADLINE,
) -> commands.CompletedRun:
    completed = ports.processes.run(
        commands.Argv.of(*argv), deadline=deadline, limit=commands.OutputLimit.default(), cwd=cwd
    )
    if not completed.succeeded:
        raise errors.PortFailure(
            port=argv[0],
            cause=f"exited with {completed.exit_code}: "
            f"{completed.stderr.decode(errors='replace').strip()}",
        )
    return completed


def output(ports: portset.HostPorts, cwd: safepaths.SafePath, *argv: str) -> str:
    return run(ports, cwd, *argv).stdout.decode(errors="replace")


def write(ports: portset.HostPorts, path: safepaths.SafePath, content: str) -> None:
    ports.files.write_atomic(path, content.encode(), mode=PLAIN)


def compile_program(
    ports: portset.HostPorts,
    bench: Bench,
    program: safepaths.SafePath,
    binary: safepaths.SafePath,
    *quieted: str,
) -> None:
    run(ports, bench.work, *COMPILE, *quieted, str(program), "-o", str(binary), *bench.flags)


def case_output(
    ports: portset.HostPorts, bench: Bench, binary: safepaths.SafePath, case: str
) -> str:
    return run(
        ports, bench.work, str(binary), case, deadline=defaults.HARNESS_CASE_DEADLINE
    ).stdout.decode(errors="replace")


def apply_patch(ports: portset.HostPorts, bench: Bench, *, reverse: bool = False) -> None:
    direction = ("-R",) if reverse else ("--forward",)
    run(ports, bench.work, *PATCH, *direction, "-p1", "-i", str(bench.patch))


def environment(ports: portset.HostPorts, bench: Bench) -> encoding.Document:
    return {
        "compiler": output(ports, bench.work, CC, "--version").splitlines()[0],
        "gio_version": output(ports, bench.work, PKG_CONFIG, "--modversion", GIO).strip(),
    }


def report(ports: portset.HostPorts, bench: Bench, found: encoding.Document) -> safepaths.SafePath:
    proof = bench.directory / defaults.RESULTS_NAME
    ports.files.write_atomic(
        proof, encoding.readable(found).encode() + b"\n", mode=defaults.RECORD_MODE
    )
    return proof

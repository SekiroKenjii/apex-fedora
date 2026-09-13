"""Write the three-line hooks that hand every decision to the rules.

Each hook is a shell line that executes the package's entry point for its own kind, so the
hook itself decides nothing and the operator can read all of it. The hooks land where Git
says this checkout's hooks live, which honours `core.hooksPath`; a hook already present
that is not one of these is left alone and named before anything is written.
"""

from __future__ import annotations

from pathlib import Path

from apex.cli import hookkinds, justfile
from apex.config import defaults
from apex.kernel import errors, refusals, safepaths
from apex.ports import files, process
from apex.workspace import gitreading

INTERPRETER = f"uv run --no-project --python {justfile.PYTHON} python"
ENTRY = f"env PYTHONPATH=src {INTERPRETER} -m apex.cli.main"


def body(kind: str) -> str:
    return f'#!/bin/sh\n{defaults.HOOK_MARKER}\nexec {ENTRY} git-hook {kind} "$@"\n'


def install(
    processes: process.ProcessPort, filesystem: files.FileSystemPort, repository: Path
) -> tuple[safepaths.SafePath, ...]:
    directory = gitreading.hooks_directory(processes, repository)
    if not filesystem.exists(directory):
        raise errors.Refusal(
            refusals.RefusalReason.HOOK_NO_REPOSITORY,
            subject=f"{directory}: no hooks directory",
            remedy="initialise the local repository first",
        )
    targets = {kind: safepaths.SafePath(directory.path / kind) for kind in hookkinds.names()}
    for target in targets.values():
        _require_ours(filesystem, target)
    for kind, target in targets.items():
        filesystem.write_atomic(target, body(kind).encode(), mode=defaults.HOOK_MODE)
    return tuple(targets.values())


def _require_ours(filesystem: files.FileSystemPort, target: safepaths.SafePath) -> None:
    """Nothing is written while any of the three is a hook somebody else installed."""
    if not filesystem.exists(target):
        return
    current = filesystem.read_bytes(target, limit=defaults.DOCUMENT_LIMIT.value)
    if defaults.HOOK_MARKER.encode() not in current:
        raise errors.Refusal(
            refusals.RefusalReason.HOOK_FOREIGN,
            subject=f"{target}: a hook that is not ours",
            remedy="move it aside, then install again",
        )

"""The reviewed locks under the checkout, read as text for a plan that only looks."""

from __future__ import annotations

from pathlib import Path

from apex.kernel import safepaths

DIRECTORY = "config"
SUFFIX = ".lock.json"


def reviewed_locks(repository: safepaths.SourceRoot) -> dict[str, str]:
    directory: Path = repository.path / DIRECTORY
    return {
        path.name: path.read_text()
        for path in sorted(directory.glob(f"*{SUFFIX}"))
        if path.is_file() and not path.is_symlink()
    }

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


class Blocked(RuntimeError):
    pass


def state_dir() -> Path:
    path = Path(os.environ.get("APEX_STATE_DIR", Path.home() / ".local/share/apex-fedora/runtime")).expanduser().absolute()
    resolved = path.resolve()
    if resolved == Path("/") or resolved == Path.home() or resolved.is_relative_to(ROOT):
        raise Blocked("Runtime state must be outside the source repository and not a home/root directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def config() -> dict:
    return json.loads((ROOT / "config/project.json").read_text())


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def output(args) -> str:
    return run(args, capture_output=True, text=True).stdout.strip()


def sha256(path: Path) -> str:
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as f:
        json.dump(value, f, indent=2)
        f.write("\n")
        name = f.name
    os.replace(name, path)


def regular_file(path: Path, *, within: Path | None = None) -> Path:
    if path.is_symlink() or not path.is_file():
        raise Blocked(f"Expected a regular file, not a device or symlink: {path}")
    resolved = path.resolve()
    if within is not None and not resolved.is_relative_to(within.resolve()):
        raise Blocked(f"File must be below {within}: {path}")
    return resolved

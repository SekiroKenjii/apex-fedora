"""Bundle the checkout for the builder; every other pipeline step is the new tree's."""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

from .common import ROOT, Blocked, sha256
from .gitguard import inspect_blob

SOURCE_PATHS = ("Containerfile", "config", "guest", "rpms", "system_files", "live", "tools")


def export_source(destination: Path) -> dict:
    files = {}
    with tarfile.open(destination, "w") as archive:
        for entry in SOURCE_PATHS:
            root = ROOT / entry
            if not root.exists():
                continue
            candidates = sorted(root.rglob("*")) if root.is_dir() else [root]
            for path in candidates:
                if path.is_dir() and not path.is_symlink():
                    continue
                if path.is_symlink() or not path.is_file():
                    raise Blocked(f"Build input is not a regular file: {path}")
                name = str(path.relative_to(ROOT))
                if "__pycache__" in path.parts:
                    continue
                data = path.read_bytes()
                inspect_blob(name, "100644", data)
                info = tarfile.TarInfo(name)
                info.size = len(data)
                info.mode = 0o755 if path.suffix == ".sh" else 0o644
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
                files[name] = sha256(path)
    return {"archive_sha256": sha256(destination), "files": files}

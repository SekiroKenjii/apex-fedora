#!/usr/bin/env python3
"""Build the guest program as a wheel and name it by its digest.

The digest printed here is the one a request carries as `agent_digest`; the guest checks it
before it runs anything. Building from a tree with uncommitted changes is allowed here and
refused where it matters: the stage that ships a wheel to a guest requires a clean tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
READ_CHUNK = 1024 * 1024


def build(out: Path, *, tree: Path = REPOSITORY) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(out), str(tree)],
        capture_output=True,
        check=True,
    )
    wheels = sorted(out.glob("*.whl"), key=lambda path: path.stat().st_mtime)
    if not wheels:
        raise RuntimeError("uv build produced no wheel")
    return wheels[-1]


def digest_of(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(READ_CHUNK), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    arguments = parser.parse_args(argv)
    wheel = build(arguments.out)
    print(json.dumps({"wheel": str(wheel), "sha256": digest_of(wheel)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

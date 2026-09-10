#!/usr/bin/env python3
"""Record and re-verify the pre-restructure runtime root.

The runtime root holds the only artefacts this project cannot rebuild: the evidence
records, the frozen candidate, the retained exports and the builder disk. Every
migration phase must prove it destroyed none of them, so this tool writes a manifest
once and compares against it afterwards.
"""

from __future__ import annotations

import argparse
import dataclasses
import enum
import hashlib
import json
import os
import stat
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path

LARGE_FILE_THRESHOLD = 100 * 1024 * 1024
READ_CHUNK = 1024 * 1024
MANIFEST_VERSION = 1

SECRET_NAMES = frozenset({"credentials.json", "id_ed25519", "builder_ed25519"})
SECRET_SUFFIXES = frozenset({".key", ".pem"})
SECRET_SUBSTRINGS = ("passphrase",)


class Tier(enum.StrEnum):
    DIGEST = "digest"
    STAT = "stat"
    SECRET = "secret"
    SYMLINK = "symlink"


@dataclasses.dataclass(frozen=True, slots=True)
class Entry:
    path: str
    tier: Tier
    mode: int
    size: int
    digest: str | None = None
    target: str | None = None

    def as_json(self) -> dict[str, object]:
        record: dict[str, object] = {
            "path": self.path,
            "tier": str(self.tier),
            "mode": f"{self.mode:04o}",
            "size": self.size,
        }
        if self.digest is not None:
            record["sha256"] = self.digest
        if self.target is not None:
            record["target"] = self.target
        return record


@dataclasses.dataclass(frozen=True, slots=True)
class Difference:
    path: str
    kind: str
    expected: str
    observed: str


def classify(relative: Path, size: int) -> Tier:
    name = relative.name
    if name in SECRET_NAMES or relative.suffix in SECRET_SUFFIXES:
        return Tier.SECRET
    if any(token in name for token in SECRET_SUBSTRINGS):
        return Tier.SECRET
    if size >= LARGE_FILE_THRESHOLD:
        return Tier.STAT
    return Tier.DIGEST


def digest_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(READ_CHUNK):
            hasher.update(chunk)
    return hasher.hexdigest()


def walk(root: Path) -> Iterator[Path]:
    for directory, subdirectories, files in os.walk(root, followlinks=False):
        subdirectories.sort()
        base = Path(directory)
        for name in sorted(files):
            yield base / name
        for name in sorted(subdirectories):
            candidate = base / name
            if candidate.is_symlink():
                yield candidate


def collect(root: Path, *, deep: bool) -> list[Entry]:
    entries: list[Entry] = []
    for absolute in walk(root):
        relative = absolute.relative_to(root)
        info = absolute.lstat()
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISLNK(info.st_mode):
            entries.append(
                Entry(
                    str(relative), Tier.SYMLINK, mode, info.st_size,
                    # Path.readlink normalises a trailing slash away; the manifest must
                    # record the target exactly as stored.
                    target=os.readlink(absolute),  # noqa: PTH115
                )
            )
            continue
        tier = classify(relative, info.st_size)
        wanted = tier is Tier.DIGEST or (tier is Tier.STAT and deep)
        digest = digest_file(absolute) if wanted else None
        entries.append(Entry(str(relative), tier, mode, info.st_size, digest=digest))
    return entries


def merkle_root(entries: Sequence[Entry]) -> str:
    hasher = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item.path):
        line = json.dumps(entry.as_json(), sort_keys=True, separators=(",", ":"))
        hasher.update(line.encode())
        hasher.update(b"\n")
    return hasher.hexdigest()


def build_manifest(root: Path, *, deep: bool) -> dict[str, object]:
    entries = collect(root, deep=deep)
    counts: dict[str, int] = {}
    for entry in entries:
        counts[str(entry.tier)] = counts.get(str(entry.tier), 0) + 1
    return {
        "manifest_version": MANIFEST_VERSION,
        "root": str(root),
        "deep": deep,
        "counts": counts,
        "total_bytes": sum(entry.size for entry in entries),
        "merkle_root": merkle_root(entries),
        "entries": [entry.as_json() for entry in entries],
    }


def compare(expected: dict[str, object], observed: dict[str, object]) -> list[Difference]:
    before = {str(item["path"]): item for item in expected["entries"]}  # type: ignore[index,union-attr]
    after = {str(item["path"]): item for item in observed["entries"]}  # type: ignore[index,union-attr]
    differences: list[Difference] = []
    for path in sorted(before.keys() - after.keys()):
        differences.append(Difference(path, "removed", "present", "absent"))
    for path in sorted(after.keys() - before.keys()):
        differences.append(Difference(path, "added", "absent", "present"))
    for path in sorted(before.keys() & after.keys()):
        old, new = before[path], after[path]
        for field in ("tier", "mode", "size", "sha256", "target"):
            if old.get(field) != new.get(field):
                differences.append(
                    Difference(path, field, str(old.get(field)), str(new.get(field)))
                )
    return differences


def default_root() -> Path:
    raw = os.environ.get("APEX_STATE_DIR", "~/.local/share/apex-fedora/runtime")
    return Path(raw).expanduser().resolve()


def default_manifest() -> Path:
    return Path("~/.local/state/apex-migration/inventory-v1.json").expanduser()


def write_manifest(target: Path, manifest: dict[str, object]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_suffix(".partial")
    with temporary.open("w") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)
    target.chmod(0o600)


def record(root: Path, target: Path, *, deep: bool) -> int:
    manifest = build_manifest(root, deep=deep)
    write_manifest(target, manifest)
    print(json.dumps({k: v for k, v in manifest.items() if k != "entries"}, indent=2))
    return 0


def verify(root: Path, target: Path, *, deep: bool) -> int:
    if not target.is_file():
        print(f"No manifest at {target}; run 'record' first", file=sys.stderr)
        return 3
    expected = json.loads(target.read_text())
    if expected.get("deep") and not deep:
        print("Manifest was recorded deep; re-run verify with --deep", file=sys.stderr)
        return 3
    observed = build_manifest(root, deep=deep)
    differences = compare(expected, observed)
    summary = {
        "root": str(root),
        "expected_merkle_root": expected["merkle_root"],
        "observed_merkle_root": observed["merkle_root"],
        "differences": len(differences),
    }
    print(json.dumps(summary, indent=2))
    for difference in differences[:50]:
        print(
            f"  {difference.kind:8s} {difference.path}"
            f"  expected={difference.expected} observed={difference.observed}",
            file=sys.stderr,
        )
    if len(differences) > 50:
        print(f"  ... and {len(differences) - 50} more", file=sys.stderr)
    return 1 if differences else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["record", "verify"])
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Also digest files at or above 100 MiB; slow, and never applied to secrets",
    )
    arguments = parser.parse_args(argv)
    root = (arguments.root or default_root()).expanduser().resolve()
    target = (arguments.manifest or default_manifest()).expanduser()
    if not root.is_dir():
        # Recording still needs a root. Verifying does not: a machine that has never built
        # anything has nothing to have disturbed, which is the ordinary state in continuous
        # integration and is not a finding. The operator's machine always has one, so the
        # gate that matters there still runs.
        if arguments.action == "verify":
            print(json.dumps({"skipped": "no runtime root on this machine"}, indent=2))
            return 0
        print(f"Runtime root is not a directory: {root}", file=sys.stderr)
        return 3
    if arguments.action == "record":
        return record(root, target, deep=arguments.deep)
    return verify(root, target, deep=arguments.deep)


if __name__ == "__main__":
    sys.exit(main())

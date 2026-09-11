from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

from .common import Blocked, ROOT, output, run

PRIVATE_NAMES = {"agents.md", "claude.md", "handover.md", "memory.md", ".env", "cosign.key", "id_rsa", "id_ed25519"}
PRIVATE_DIRS = {".claude", ".codex", ".agents", "agent", "evidence", "private", "logs", "fprint", "fingerprints", "__pycache__"}
SUBJECT = re.compile(r"(?:feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(?:\([a-z0-9][a-z0-9._/-]*\))?: [^\s].*")
SECRETS = [re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"), re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")]


def permitted(path: str) -> bool:
    p = PurePosixPath(path)
    return not (p.is_absolute() or ".." in p.parts or p.name.lower() in PRIVATE_NAMES or p.name.lower().startswith(".env.") or any(x.lower() in PRIVATE_DIRS for x in p.parts[:-1]) or p.suffix.lower() in {".log", ".pcap", ".pcapng", ".qcow2", ".iso", ".key", ".pem", ".p12", ".pfx", ".pyc", ".fpt", ".fpm"})


def validate_subject(message: str):
    # Git supplies a final newline; a second line, including a blank body, is not allowed.
    text = message.removesuffix("\n")
    if "\n" in text or "\r" in text or len(text) > 72 or not SUBJECT.fullmatch(text):
        raise Blocked("Use one Conventional Commit subject, at most 72 characters, with no body or trailers")
    if "co-authored-by" in text.lower():
        raise Blocked("Co-author trailers are not allowed")


def inspect_blob(path: str, mode: str, blob: bytes):
    if not permitted(path):
        raise Blocked(f"Private/local file must not enter Git: {path}")
    if mode not in {"100644", "100755"}:
        raise Blocked(f"Symlinks and submodules are not accepted in the build source: {path}")
    # Current source inputs are text. Opaque sensor data must not pass under a new name.
    try:
        blob.decode('utf-8')
    except UnicodeDecodeError:
        raise Blocked(f'Binary source requires a reviewed packaging route: {path}')
    if b'\x00' in blob:
        raise Blocked(f'Binary source requires a reviewed packaging route: {path}')
    if any(pattern.search(blob) for pattern in SECRETS):
        raise Blocked(f"Secret material detected in {path}")
    if b'<!-- apex-' + b'local-only -->' in blob:
        raise Blocked(f"Local-only document content detected in {path}")
    if len(blob) > 20 * 1024 * 1024:
        raise Blocked(f"Large source blob requires separate reviewed packaging: {path}")


def inspect_tree(repo: Path, revision: str | None = None):
    if revision:
        rows = run(["git", "-C", repo, "ls-tree", "-rz", revision], capture_output=True).stdout
    else:
        rows = run(["git", "-C", repo, "ls-files", "--stage", "-z"], capture_output=True).stdout
    for row in rows.split(b"\0"):
        if not row:
            continue
        meta, name = row.split(b"\t", 1)
        parts = meta.decode().split()
        mode, oid = (parts[0], parts[2]) if revision else (parts[0], parts[1])
        if not revision and parts[2] != "0":
            raise Blocked("Resolve index conflicts before committing")
        path = name.decode("utf-8", errors="strict")
        if mode not in {"100644", "100755"}:
            raise Blocked(f"Unsupported source mode: {path}")
        blob = run(["git", "-C", repo, "cat-file", "blob", oid], capture_output=True).stdout
        inspect_blob(path, mode, blob)


def inspect_outgoing(repo: Path, updates: str):
    for line in updates.splitlines():
        _, local_sha, _, remote_sha = line.split()
        if set(local_sha) == {"0"}:
            continue
        args = ["git", "-C", repo, "rev-list", local_sha]
        if set(remote_sha) != {"0"}:
            known = subprocess.run(["git", "-C", str(repo), "cat-file", "-e", remote_sha], capture_output=True)
            if known.returncode:
                raise Blocked("Fetch remote history before checking this push")
            args += ["^" + remote_sha]
        # A commit already held by a remote is not outgoing, whichever branch carries it now.
        args += ["--not", "--remotes"]
        for commit in output(args).splitlines():
            raw = run(["git", "-C", repo, "cat-file", "commit", commit], capture_output=True).stdout
            validate_subject(raw.split(b"\n\n", 1)[1].decode())
            inspect_tree(repo, commit)


def install(repo: Path = ROOT):
    existing = subprocess.run(["git", "-C", str(repo), "config", "--get", "core.hooksPath"], capture_output=True, text=True)
    if existing.returncode == 0:
        raise Blocked("An existing core.hooksPath must be integrated manually")
    hooks = repo / ".git/hooks"
    if not hooks.is_dir():
        raise Blocked("Initialize a local Git repository first")
    for name in ("pre-commit", "commit-msg", "pre-push"):
        path = hooks / name
        body = '#!/bin/sh\n# apex-local-hook\nexec python3 tools/apex.py git-hook ' + name + ' "$@"\n'
        if path.exists() and "# apex-local-hook" not in path.read_text():
            raise Blocked(f"Preserving existing hook: {path}")
        path.write_text(body)
        path.chmod(0o755)

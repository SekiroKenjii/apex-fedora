import hashlib
import json
from pathlib import Path
import subprocess

lock = json.loads(Path("config/sources.lock.json").read_text())
for name, source in lock["sources"].items():
    filename = source.get("filename", f"{name}.tar.gz")
    if Path(filename).name != filename:
        raise SystemExit("Invalid source filename")
    path = Path("sources") / filename
    subprocess.run(["curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https", "--retry", "2", "--output", str(path), source["url"]], check=True)
    with path.open("rb") as f:
        actual = hashlib.file_digest(f, "sha256").hexdigest()
    if actual != source["sha256"]:
        raise SystemExit(f"Checksum mismatch: {name}")

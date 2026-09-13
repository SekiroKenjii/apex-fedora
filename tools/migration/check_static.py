#!/usr/bin/env python3
"""Validate source syntax without running guest scripts or importing host state."""

import ast
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[2]
count = 0
for name in ("tools", "guest", "system_files", "live", "config", "tests"):
    for path in sorted((root / name).rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix == ".sh":
            subprocess.run(["bash", "-n", str(path)], check=True)
        elif path.suffix == ".py":
            ast.parse(path.read_text(), filename=str(path))
        elif path.suffix == ".json":
            json.loads(path.read_text())
        else:
            continue
        count += 1
print(f"Syntax checked: {count} files")

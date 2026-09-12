#!/usr/bin/env python3
"""Prove the new entry point behaves exactly like the one it will replace.

`tools/apex.py` is what the justfile, the git hooks and habit all invoke today. The
installed `apex` console script has to produce the same exit code and the same bytes before
anything is rewired to it.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from migration import golden_corpus, synthetic_root

REPOSITORY = Path(__file__).resolve().parents[2]
LEGACY = REPOSITORY / "tools" / "apex.py"
MODERN = ("-c", "import sys; from apex.cli.main import main; sys.exit(main())")
TIMEOUT = 60


def invocation_arguments() -> list[list[str]]:
    arguments = []
    for invocation in golden_corpus.invocations():
        if "<subject>" in invocation.arguments:
            continue
        arguments.append(list(invocation.arguments))
    return arguments


def execute(command: list[str], arguments: list[str], root: Path) -> dict[str, object]:
    environment = dict(os.environ)
    environment["APEX_STATE_DIR"] = str(root)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONPATH"] = str(REPOSITORY / "src")
    environment["COLUMNS"] = "100"
    completed = subprocess.run(
        [sys.executable, *command, *arguments],
        capture_output=True, text=True, timeout=TIMEOUT, env=environment, cwd=REPOSITORY,
    )
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


@dataclasses.dataclass(frozen=True, slots=True)
class Difference:
    arguments: list[str]
    field: str


def compare(scratch: Path) -> list[Difference]:
    root = synthetic_root.build(scratch / "root")
    differences: list[Difference] = []
    for arguments in invocation_arguments():
        legacy = execute([str(LEGACY)], arguments, root)
        modern = execute(list(MODERN), arguments, root)
        for field in ("exit_code", "stdout", "stderr"):
            if legacy[field] != modern[field]:
                differences.append(Difference(arguments=arguments, field=field))
    return differences


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, required=True)
    arguments = parser.parse_args(argv)
    scratch = arguments.scratch.expanduser().resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    differences = compare(scratch)
    summary = {"compared": len(invocation_arguments()), "differences": len(differences)}
    print(json.dumps(summary, indent=2))
    for difference in differences:
        print(f"  {' '.join(difference.arguments)}: {difference.field}", file=sys.stderr)
    return 1 if differences else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Freeze the justfile rendered from the command registry, or check that nothing drifted.

`check` holds one equality: the committed `Justfile` equals a fresh rendering, so a recipe
that names a command is rendered from that command's own declaration and a recipe nobody
declares cannot appear by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))

from apex.cli import justfile  # noqa: E402

TARGET = REPOSITORY / "Justfile"


def freeze() -> int:
    TARGET.write_text(justfile.render())
    print(json.dumps({"frozen": TARGET.name}, indent=2))
    return 0


def check() -> int:
    drifted = TARGET.read_text() != justfile.render() if TARGET.is_file() else True
    print(json.dumps({"justfile": TARGET.name, "drifted": drifted}, indent=2))
    return 1 if drifted else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "check"])
    arguments = parser.parse_args(argv)
    return freeze() if arguments.action == "freeze" else check()


if __name__ == "__main__":
    raise SystemExit(main())

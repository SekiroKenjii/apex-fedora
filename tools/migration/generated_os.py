#!/usr/bin/env python3
"""Freeze the generated build inputs under `generated/os/`, or check that nothing drifted.

`check` holds two equalities: every rendered file equals its frozen copy, so re-rendering
changes no byte, and every rendered file equals the handwritten file it replaces, which is
gate G8 for as long as that file ships.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY / "src"))

from apex.generating import osoutputs  # noqa: E402

DIRECTORY = REPOSITORY / osoutputs.DIRECTORY


def freeze() -> int:
    for name, payload in osoutputs.rendered().items():
        target = DIRECTORY / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    print(json.dumps({"frozen": sorted(output.name for output in osoutputs.OUTPUTS)}, indent=2))
    return 0


def differences() -> list[str]:
    found = []
    rendered = osoutputs.rendered()
    for output in osoutputs.OUTPUTS:
        frozen = DIRECTORY / output.name
        handwritten = REPOSITORY / output.handwritten
        if not frozen.is_file():
            found.append(f"{output.name}: no frozen copy")
        elif frozen.read_bytes() != rendered[output.name]:
            found.append(f"{output.name}: the frozen copy differs from the rendering")
        if handwritten.is_file() and handwritten.read_bytes() != rendered[output.name]:
            found.append(f"{output.name}: the rendering differs from {output.handwritten}")
    return found


def check() -> int:
    found = differences()
    print(json.dumps({"outputs": len(osoutputs.OUTPUTS), "differences": found}, indent=2))
    return 1 if found else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "check"])
    arguments = parser.parse_args(argv)
    return freeze() if arguments.action == "freeze" else check()


if __name__ == "__main__":
    raise SystemExit(main())

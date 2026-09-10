#!/usr/bin/env python3
"""Read the real store through the versioned reader and report what it holds.

The shadow gate compares verdicts and cannot see anything else, so a damaged, symlinked or
unbound record is invisible to it. This exits non-zero on any intake fault, which is what makes
the reader's error handling gated rather than merely tested.

Read only. Nothing here writes, and no path under the runtime root is created.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPOSITORY / "src")]

from apex.attestation import columns, readiness, reading, resolving, retracting  # noqa: E402
from apex.cli import rendering  # noqa: E402
from apex.kernel import errors  # noqa: E402


def tabulate(runtime_root: Path, *, strict: bool) -> columns.Table:
    found = reading.read_store(runtime_root)
    outcome = readiness.evaluate(
        required=resolving.required_environments(),
        records=found.records,
        candidate=found.candidate,
    )
    withheld: tuple[retracting.Withheld, ...] = ()
    if strict:
        outcome, withheld = retracting.retract(outcome, attestations=found.attestations)
    return columns.tabulate(
        reading=found, outcome=outcome, withheld=withheld, strict=strict
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)
    root = (arguments.root or Path("~/.local/share/apex-fedora/runtime")).expanduser()
    if not (root / "candidate.json").is_file():
        print(json.dumps({"skipped": "no candidate in this runtime root"}, indent=2))
        return 0
    try:
        table = tabulate(root, strict=arguments.strict)
    except errors.ApexError as failure:
        print(json.dumps({"refused": str(failure)}, indent=2), file=sys.stderr)
        return failure.exit_code
    if arguments.json:
        print(json.dumps(columns.document(table), indent=2))
    else:
        print(rendering.render(table), end="")
    if table.faults:
        print(f"{len(table.faults)} intake faults", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

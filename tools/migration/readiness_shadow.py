#!/usr/bin/env python3
"""Compare the new readiness fold with the one it will replace.

Both sides are read only. The legacy `evaluate` is a pure read and the new fold does no input
or output at all, so running this changes nothing in the store. Legacy stays the authority
until cutover; this only proves the two agree.

One divergence is intended and is therefore named rather than hidden. When a cited proof no
longer matches its digest, legacy drops the record and the check falls back to not tested,
recording the problem in a separate error list that the verdict does not reflect. The new
fold blocks it. A detected fault and a check nobody ran must not be the same value, so this
class is accepted; anything else fails the gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPOSITORY / "src"), str(REPOSITORY / "tools")]

from apex.adapters.real import real_files  # noqa: E402
from apex.attestation import readiness, resolving  # noqa: E402
from apexlib import evidence as legacy  # noqa: E402


def compare(runtime_root: Path) -> dict[str, object]:
    records, candidate = resolving.resolve_store(runtime_root, files=real_files.LocalFiles())
    fresh = readiness.evaluate(
        required=resolving.required_environments(), records=records, candidate=candidate
    )
    stored = legacy.evaluate(runtime_root, str(candidate) if candidate else None)

    flagged = {error.split(":", 1)[0].removesuffix(".json") for error in stored["errors"]}
    accepted, unexpected = [], []
    for group in stored["checks"].values():
        for name, record in group.items():
            mine = fresh.verdicts.get(name)
            observed = mine.stored_name if mine else "ABSENT"
            if observed == record["status"]:
                continue
            entry = {"check": name, "legacy": record["status"], "new": observed}
            if name in flagged and record["status"] == "NOT TESTED" and observed == "BLOCKED":
                accepted.append(entry)
            else:
                unexpected.append(entry)
    for name in fresh.verdicts:
        if not any(name in group for group in stored["checks"].values()):
            unexpected.append({"check": name, "legacy": "ABSENT", "new": "present"})

    return {
        "candidate": str(candidate) if candidate else None,
        "legacy_ready": stored["ready_to_install"],
        "new_ready": fresh.ready,
        "counts": dict(sorted(fresh.counts.items())),
        "faults": list(fresh.faults),
        "accepted_divergences": accepted,
        "disagreements": unexpected,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None)
    arguments = parser.parse_args(argv)
    root = (arguments.root or Path("~/.local/share/apex-fedora/runtime")).expanduser()
    if not (root / "candidate.json").is_file():
        print(json.dumps({"skipped": "no candidate in this runtime root"}, indent=2))
        return 0
    result = compare(root)
    print(json.dumps(result, indent=2))
    if result["disagreements"] or result["legacy_ready"] != result["new_ready"]:
        print("The two readiness folds disagree", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Hold new code to the house style while the old tree is still being replaced.

The count is kept per file. A file that is not in the baseline must report nothing, so
every file written from now on is clean without anyone having to remember. A file that is
in the baseline may improve but never regress.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tomllib
from collections.abc import Sequence
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
BASELINE = REPOSITORY / "generated" / "lint-ratchet.json"
TARGETS = ("src", "tools", "guest", "tests", "system_files")
RUFF = ("uv", "run", "--no-project", "--with", "ruff==0.14.5", "ruff")


def configuration_digest() -> str:
    """A baseline is only meaningful under the configuration that produced it."""
    document = tomllib.loads((REPOSITORY / "pyproject.toml").read_text())
    ruff = document.get("tool", {}).get("ruff", {})
    canonical = json.dumps(ruff, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def counts() -> dict[str, int]:
    completed = subprocess.run(
        [*RUFF, "check", *TARGETS, "--output-format", "json"],
        capture_output=True,
        text=True,
        cwd=REPOSITORY,
    )
    if completed.returncode not in (0, 1):
        raise RuntimeError(completed.stderr.strip())
    tally: dict[str, int] = {}
    for finding in json.loads(completed.stdout or "[]"):
        relative = str(Path(finding["filename"]).relative_to(REPOSITORY))
        tally[relative] = tally.get(relative, 0) + 1
    return tally


def freeze() -> int:
    tally = counts()
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    with BASELINE.open("w") as handle:
        json.dump(
            {"configuration": configuration_digest(), "files": dict(sorted(tally.items()))},
            handle,
            indent=1,
            sort_keys=True,
        )
        handle.write("\n")
    print(json.dumps({"files": len(tally), "findings": sum(tally.values())}, indent=2))
    return 0


def regressions(baseline: dict[str, int], observed: dict[str, int]) -> list[str]:
    problems = []
    for path, count in sorted(observed.items()):
        allowed = baseline.get(path)
        if allowed is None:
            problems.append(f"{path}: {count} findings in a file the ratchet expects to be clean")
        elif count > allowed:
            problems.append(f"{path}: {count} findings, baseline allows {allowed}")
    return problems


def check() -> int:
    document = json.loads(BASELINE.read_text())
    recorded = document.get("configuration")
    current = configuration_digest()
    if recorded != current:
        print(
            f"The lint configuration changed since the baseline was frozen "
            f"({recorded} to {current}). Re-freeze it and say why in the phase log.",
            file=sys.stderr,
        )
        return 1
    baseline = document["files"]
    observed = counts()
    problems = regressions(baseline, observed)
    improved = sum(
        baseline[path] - observed.get(path, 0)
        for path in baseline
        if baseline[path] > observed.get(path, 0)
    )
    print(
        json.dumps(
            {
                "baseline_findings": sum(baseline.values()),
                "observed_findings": sum(observed.values()),
                "removed_since_baseline": improved,
                "regressions": len(problems),
            },
            indent=2,
        )
    )
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "check"])
    arguments = parser.parse_args(argv)
    return freeze() if arguments.action == "freeze" else check()


if __name__ == "__main__":
    sys.exit(main())

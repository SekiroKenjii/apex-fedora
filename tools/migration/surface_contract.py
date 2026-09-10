#!/usr/bin/env python3
"""Freeze and check the command surface the operator actually types.

Every later phase may add a recipe. None may rename one, drop one, or change the operands
an existing one takes. The frozen contract is taken from the pre-restructure baseline, so
it describes habit rather than whatever the working tree happens to contain.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
CONTRACT = REPOSITORY / "generated" / "justfile.surface.json"
BASELINE_REVISION = "pre-restructure"


@dataclasses.dataclass(frozen=True, slots=True)
class Parameter:
    name: str
    required: bool

    def as_json(self) -> dict[str, object]:
        return {"name": self.name, "required": self.required}


@dataclasses.dataclass(frozen=True, slots=True)
class Recipe:
    name: str
    parameters: tuple[Parameter, ...]

    def as_json(self) -> dict[str, object]:
        return {"name": self.name, "parameters": [item.as_json() for item in self.parameters]}

    @property
    def required_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.parameters if item.required)


def dump(justfile: Path) -> dict[str, Recipe]:
    completed = subprocess.run(
        ["just", "--justfile", str(justfile), "--dump", "--dump-format", "json"],
        capture_output=True, text=True, check=True, cwd=justfile.parent,
    )
    document = json.loads(completed.stdout)
    recipes = {}
    for name, body in document["recipes"].items():
        if body["private"]:
            continue
        parameters = tuple(
            Parameter(item["name"], item["default"] is None and item["kind"] != "star")
            for item in body["parameters"]
        )
        recipes[name] = Recipe(name, parameters)
    return recipes


def baseline_justfile(revision: str, scratch: Path) -> Path:
    content = subprocess.run(
        ["git", "show", f"{revision}:Justfile"],
        capture_output=True, text=True, check=True, cwd=REPOSITORY,
    ).stdout
    scratch.mkdir(parents=True, exist_ok=True)
    target = scratch / "Justfile"
    target.write_text(content)
    return target


def violations(frozen: dict[str, Recipe], live: dict[str, Recipe]) -> list[str]:
    problems = []
    for name, recipe in sorted(frozen.items()):
        current = live.get(name)
        if current is None:
            problems.append(f"{name}: recipe was removed or renamed")
            continue
        if current.required_names != recipe.required_names:
            problems.append(
                f"{name}: operands changed from {list(recipe.required_names)}"
                f" to {list(current.required_names)}"
            )
    return problems


def freeze(revision: str, scratch: Path) -> int:
    recipes = dump(baseline_justfile(revision, scratch))
    document = {
        "revision": revision,
        "recipes": [recipes[name].as_json() for name in sorted(recipes)],
    }
    CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    with CONTRACT.open("w") as handle:
        json.dump(document, handle, indent=1, sort_keys=True)
        handle.write("\n")
    print(json.dumps({"revision": revision, "recipes": len(recipes)}, indent=2))
    return 0


def check() -> int:
    document = json.loads(CONTRACT.read_text())
    frozen = {
        str(item["name"]): Recipe(
            str(item["name"]),
            tuple(Parameter(str(p["name"]), bool(p["required"])) for p in item["parameters"]),
        )
        for item in document["recipes"]
    }
    live = dump(REPOSITORY / "Justfile")
    problems = violations(frozen, live)
    print(
        json.dumps(
            {"frozen": len(frozen), "live": len(live), "added": len(live) - len(frozen),
             "violations": len(problems)},
            indent=2,
        )
    )
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    return 1 if problems else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "check"])
    parser.add_argument("--revision", default=BASELINE_REVISION)
    parser.add_argument("--scratch", type=Path)
    arguments = parser.parse_args(argv)
    if arguments.action == "check":
        return check()
    if arguments.scratch is None:
        parser.error("freeze needs --scratch")
    return freeze(arguments.revision, arguments.scratch.expanduser().resolve())


if __name__ == "__main__":
    sys.exit(main())

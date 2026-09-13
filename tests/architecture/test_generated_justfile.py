"""The committed justfile equals a fresh rendering, and keeps the frozen operator surface."""

from __future__ import annotations

import json
from pathlib import Path

from apex.cli import justfile, legacy_bridge

REPOSITORY = Path(__file__).resolve().parents[2]
JUSTFILE = REPOSITORY / "Justfile"
SURFACE = REPOSITORY / "generated" / "justfile.surface.json"
LEGACY = "python3 tools/apex.py "


def test_the_committed_justfile_equals_a_fresh_rendering() -> None:
    assert JUSTFILE.read_text() == justfile.render()


def test_every_frozen_recipe_is_still_rendered() -> None:
    frozen = {str(item["name"]) for item in json.loads(SURFACE.read_text())["recipes"]}
    heads = {line.split(" ")[0].rstrip(":") for line in JUSTFILE.read_text().splitlines()
             if line and not line.startswith((" ", "#", "set ", "export ")) and ":" in line}

    assert frozen <= heads


def test_no_recipe_calls_the_older_tree_for_a_retired_or_owned_command() -> None:
    for line in JUSTFILE.read_text().splitlines():
        stripped = line.strip()
        if not stripped.startswith(LEGACY):
            continue
        name = stripped.removeprefix(LEGACY).split(" ")[0]

        assert legacy_bridge.handles(name), f"{name} is not bridged any more"

"""The committed justfile equals a fresh rendering, and keeps the frozen operator surface."""

from __future__ import annotations

import json
from pathlib import Path

from apex.cli import justfile

REPOSITORY = Path(__file__).resolve().parents[2]
JUSTFILE = REPOSITORY / "Justfile"
SURFACE = REPOSITORY / "generated" / "justfile.surface.json"


def test_the_committed_justfile_equals_a_fresh_rendering() -> None:
    assert JUSTFILE.read_text() == justfile.render()


def test_every_frozen_recipe_is_still_rendered() -> None:
    frozen = {str(item["name"]) for item in json.loads(SURFACE.read_text())["recipes"]}
    heads = {
        line.split(" ")[0].rstrip(":")
        for line in JUSTFILE.read_text().splitlines()
        if line and not line.startswith((" ", "#", "set ", "export ")) and ":" in line
    }

    assert frozen <= heads

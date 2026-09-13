#!/usr/bin/env python3
"""Keep a readable copy of every recipe's derived plan under version control.

The plan is derived, so nobody edits the copy by hand. Freezing it makes a change to the
stage graph a diff a reviewer reads, and checking it makes an unreviewed change fail the gate.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPOSITORY / "src")]

from apex.composition.recipes import (  # noqa: E402
    disk_artifact_recipe,
    export_source_recipe,
    image_recipe,
    live_artifact_recipe,
    nvidia_recipe,
)
from apex.pipeline import plans  # noqa: E402
from apex.verification.recipes import (  # noqa: E402
    desktop_render_recipe,
    desktop_theme_recipe,
    fingerprint_cleanup_recipe,
    installer_diagnostics_recipe,
    installer_fixtures_recipe,
    installer_payload_recipe,
    installer_trust_recipe,
    live_lock_recipe,
    live_observe_recipe,
    live_protection_recipe,
    ventoy_observe_recipe,
)

DIRECTORY = REPOSITORY / "generated" / "plans"
RECIPES = {
    export_source_recipe.NAME: export_source_recipe.PLAN,
    image_recipe.NAME: image_recipe.PLAN,
    disk_artifact_recipe.NAME: disk_artifact_recipe.PLAN,
    live_artifact_recipe.NAME: live_artifact_recipe.PLAN,
    nvidia_recipe.NAME: nvidia_recipe.PLAN,
    live_protection_recipe.NAME: live_protection_recipe.PLAN,
    desktop_theme_recipe.NAME: desktop_theme_recipe.PLAN,
    desktop_render_recipe.NAME: desktop_render_recipe.PLAN,
    fingerprint_cleanup_recipe.NAME: fingerprint_cleanup_recipe.PLAN,
    installer_trust_recipe.NAME: installer_trust_recipe.PLAN,
    live_observe_recipe.NAME: live_observe_recipe.PLAN,
    ventoy_observe_recipe.NAME: ventoy_observe_recipe.PLAN,
    live_lock_recipe.NAME: live_lock_recipe.PLAN,
    installer_payload_recipe.NAME: installer_payload_recipe.PLAN,
    installer_diagnostics_recipe.NAME: installer_diagnostics_recipe.PLAN,
    installer_fixtures_recipe.NAME: installer_fixtures_recipe.PLAN,
}


def rendered(name: str) -> str:
    return json.dumps(plans.render(RECIPES[name]), indent=1, sort_keys=True) + "\n"


def freeze() -> int:
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    for name in RECIPES:
        (DIRECTORY / f"{name}.json").write_text(rendered(name))
    print(json.dumps({"frozen": sorted(RECIPES)}, indent=2))
    return 0


def differences() -> list[str]:
    found = []
    for name in RECIPES:
        path = DIRECTORY / f"{name}.json"
        if not path.is_file():
            found.append(f"{name}: no frozen plan")
        elif path.read_text() != rendered(name):
            found.append(f"{name}: the frozen plan differs from the derived one")
    return found


def check() -> int:
    found = differences()
    print(json.dumps({"plans": sorted(RECIPES), "differences": found}, indent=2))
    return 1 if found else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["freeze", "check"])
    arguments = parser.parse_args(argv)
    return freeze() if arguments.action == "freeze" else check()


if __name__ == "__main__":
    sys.exit(main())

"""Adding the next release is adding one file, and planning the move touches nothing else.

The acceptance in the specification: create the next profile, run the upgrade plan, and no
other Python file changes. The profile is written for the length of the test and removed,
and the plan runs in a fresh interpreter so the registry discovers it the way a real run
would.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from apex.kernel import identifiers
from apex.targeting import upgrading
from apex.targeting.releases import fedora44_release

REPOSITORY = Path(__file__).resolve().parents[2]
RELEASES = REPOSITORY / "src" / "apex" / "targeting" / "releases"
TARGET = identifiers.ProfileId("fedora-45")


def apex(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = {
        **os.environ, "PYTHONPATH": str(REPOSITORY / "src"), "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(
        [sys.executable, "-m", "apex.cli.main", *arguments],
        capture_output=True, text=True, env=environment, cwd=REPOSITORY, check=False, timeout=120,
    )


def test_the_next_release_is_one_new_file_and_the_plan_names_what_moves() -> None:
    module = RELEASES / upgrading.module_name(TARGET)
    assert not module.exists()
    before = {path: path.stat().st_mtime_ns for path in REPOSITORY.rglob("*.py")}
    absent = apex("plan", "upgrade", "--release", str(TARGET))
    assert absent.returncode == 3, absent.stderr
    module.write_text(absent.stdout.replace("supported=False", "supported=False"))
    try:
        planned = apex("plan", "upgrade", "--release", str(TARGET))
    finally:
        module.unlink()
    assert planned.returncode == 0, planned.stderr
    document = json.loads(planned.stdout)
    assert document["target"] == "fedora-45" and document["current"] == "fedora-44"
    assert [change["field"] for change in document["changes"]] == ["id", "supported"]
    assert document["writes"] == []
    after = {path: path.stat().st_mtime_ns for path in REPOSITORY.rglob("*.py")}
    assert after == before


def test_the_template_carries_the_current_profile_s_values_for_revision() -> None:
    text = upgrading.template(TARGET, fedora44_release.PROFILE)

    assert f'mock_root="{fedora44_release.PROFILE.mock_root}"' in text

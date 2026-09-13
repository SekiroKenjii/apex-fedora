"""Which guard decides a commit message, driven the way Git drives it.

These run the package's entry point as a program, so they see what the operator sees: the
exit code, the two streams, and nothing else. A test that called the rules directly would
pass just as happily with the hook pointed elsewhere. When the rules cannot be imported at
all, the hook fails closed: nothing is permitted, and the reason is on standard error.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
SWITCH = "APEX_GUARD"
LEGACY = "legacy"


def commit_message(tmp_path: Path, text: str) -> Path:
    target = tmp_path / "COMMIT_EDITMSG"
    target.write_text(text)
    return target


def hook(
    message: Path, *, environment: dict[str, str] | None = None, source: Path | None = None
) -> tuple[int, str, str]:
    combined = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(REPOSITORY / "src" if source is None else source),
    }
    combined.update(environment or {})
    done = subprocess.run(
        [sys.executable, "-m", "apex.cli.main", "git-hook", "commit-msg", str(message)],
        capture_output=True,
        text=True,
        cwd=str(REPOSITORY),
        env=combined,
    )
    return done.returncode, done.stdout, done.stderr


def test_a_malformed_subject_is_refused_by_the_rule_that_refused_it(tmp_path: Path) -> None:
    code, out, err = hook(commit_message(tmp_path, "update product\n"))

    assert code == 2
    assert out == ""
    assert err.startswith("BLOCKED: commit.subject-malformed: update product;")


def test_every_rule_that_refuses_one_message_is_reported_in_one_pass(tmp_path: Path) -> None:
    message = commit_message(tmp_path, "nope: hi\n\nCo-authored-by: someone\n")

    code, _, err = hook(message)

    assert code == 2
    assert "commit.subject-malformed" in err
    assert "commit.has-body" in err
    assert "commit.co-author-trailer" in err


def test_a_subject_carrying_a_line_break_never_breaks_the_line_structure(
    tmp_path: Path,
) -> None:
    code, _, err = hook(commit_message(tmp_path, "fix(audio): one\rtwo\n"))

    assert code == 2
    assert "\r" not in err


def test_a_conventional_subject_is_permitted_silently(tmp_path: Path) -> None:
    """The whole tuple, so an implementation cannot pass by refusing everything."""
    message = commit_message(tmp_path, "feat(cli): answer a hook from the rules\n")

    assert hook(message) == (0, "", "")


def test_the_refusal_names_the_rule_and_offers_no_way_around_it(tmp_path: Path) -> None:
    _, _, err = hook(commit_message(tmp_path, "update product\n"))

    assert f"{SWITCH}={LEGACY}" not in err
    assert "the rule that refused is named above" in err


def test_the_retired_switch_is_an_unknown_setting_and_permits_nothing(tmp_path: Path) -> None:
    """The escape hatch is gone: the variable is refused as a setting nobody declared."""
    code, out, err = hook(
        commit_message(tmp_path, "feat(cli): a message the rules would permit\n"),
        environment={SWITCH: LEGACY},
    )

    assert code == 2 and out == ""
    assert "settings.unknown: APEX_GUARD" in err
    assert "Conventional Commit" not in err


def test_without_the_rules_the_hook_fails_closed(tmp_path: Path) -> None:
    """No older guard stands behind the rules: unreachable rules permit nothing."""
    empty = tmp_path / "no-package"
    empty.mkdir()

    code, out, err = hook(
        commit_message(tmp_path, "feat(cli): a message the rules would permit\n"), source=empty
    )

    assert code != 0
    assert out == ""
    assert "No module named" in err

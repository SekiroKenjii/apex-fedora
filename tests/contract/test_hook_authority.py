"""Which guard decides a commit message, driven the way Git drives it.

These run the installed entry point as a program, so they see what the operator sees: the exit
code, the two streams, and nothing else. A test that called the rules directly would pass just as
happily with the transfer switched off.

Any sentinel literal added here must be split the way `tests/test_gitguard.py` splits its own, or
the repository's own rules refuse the file that tests them.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
ENTRY = REPOSITORY / "tools" / "apex.py"
SWITCH = "APEX_GUARD"
LEGACY = "legacy"


def commit_message(tmp_path: Path, text: str) -> Path:
    target = tmp_path / "COMMIT_EDITMSG"
    target.write_text(text)
    return target


def hook(
    message: Path, *, environment: dict[str, str] | None = None, root: Path | None = None
) -> tuple[int, str, str]:
    entry = (root or REPOSITORY) / "tools" / "apex.py"
    combined = {"PATH": os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
    combined.update(environment or {})
    done = subprocess.run(
        [sys.executable, str(entry), "git-hook", "commit-msg", str(message)],
        capture_output=True,
        text=True,
        cwd=str(root or REPOSITORY),
        env=combined,
    )
    return done.returncode, done.stdout, done.stderr


def test_a_malformed_subject_is_refused_by_the_rule_that_refused_it(tmp_path: Path) -> None:
    code, out, err = hook(commit_message(tmp_path, "update product\n"))

    assert code == 2
    assert out == ""
    assert err.startswith("BLOCKED: commit.subject-malformed: update product;")


def test_every_rule_that_refuses_one_message_is_reported_in_one_pass(tmp_path: Path) -> None:
    """The guard being replaced raises on the first failure and hides the rest."""
    message = commit_message(tmp_path, "nope: hi\n\nCo-authored-by: someone\n")

    code, _, err = hook(message)

    assert code == 2
    assert "3 rules refuse this commit message" in err
    for rule in ("commit.subject-malformed", "commit.has-body", "commit.co-author-trailer"):
        assert rule in err


def test_a_subject_carrying_a_line_break_never_breaks_the_line_structure(
    tmp_path: Path,
) -> None:
    """The break is escaped into the line rather than splitting it.

    A carriage return does not survive reading the file: Python translates it, and the guard
    being replaced reads the same way, so this arrives as an ordinary second line. What is being
    checked is the renderer, which must never emit a fragment that carries no prefix.
    """
    code, _, err = hook(commit_message(tmp_path, "fix: a\rb\n"))

    assert code == 2
    assert "\\n" in err
    for line in err.splitlines():
        assert line.startswith(("BLOCKED: ", "  ", "If this refusal"))


def test_a_conventional_subject_is_permitted_silently(tmp_path: Path) -> None:
    """The whole tuple, so an implementation cannot pass by refusing everything."""
    message = commit_message(tmp_path, "feat(cli): answer a hook from the rules\n")

    assert hook(message) == (0, "", "")


def test_the_refusal_says_what_to_do_when_it_is_wrong(tmp_path: Path) -> None:
    _, _, err = hook(commit_message(tmp_path, "update product\n"))

    assert f"{SWITCH}={LEGACY}" in err


def test_the_switch_hands_the_verdict_back_to_the_previous_guard(tmp_path: Path) -> None:
    code, _, err = hook(
        commit_message(tmp_path, "update product\n"), environment={SWITCH: LEGACY}
    )

    assert code == 2
    assert "Conventional Commit" in err
    assert "commit.subject-malformed" not in err


def test_the_previous_guard_still_decides_when_the_rules_are_absent(tmp_path: Path) -> None:
    """A checkout holding only the older tree must still refuse a bad message."""
    root = tmp_path / "partial"
    root.mkdir()
    shutil.copytree(
        REPOSITORY / "tools", root / "tools", ignore=shutil.ignore_patterns("__pycache__")
    )

    code, _, err = hook(commit_message(tmp_path, "update product\n"), root=root)

    assert code == 2
    assert "Conventional Commit" in err
    assert "not checked out" in err

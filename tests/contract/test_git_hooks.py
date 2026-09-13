"""The pre-commit and pre-push hooks against a real repository, through the real process port.

Any sentinel literal here is split the way the guard's own tests split theirs, so the
repository's rules do not refuse the file that tests them.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from apex.adapters.real import real_files, real_process
from apex.cli import hookdispatch, hookinstall
from apex.config import defaults
from apex.kernel import errors, refusals

NONE = "0" * 40


def git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=True,
        env={
            "PATH": "/usr/bin:/bin",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@x",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@x",
            "HOME": str(repository),
        },
    ).stdout


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    git(checkout, "init", "-q", "-b", "main")
    (checkout / "src").mkdir()
    (checkout / "src" / "a.py").write_text("value = 1\n")
    git(checkout, "add", "src/a.py")
    git(checkout, "commit", "-q", "-m", "feat(src): the first file")
    return checkout


def run(repository: Path, kind: str, stdin: str = "") -> tuple[int, str]:
    return hookdispatch.run(
        [kind], stdin, processes=real_process.SubprocessRunner(), repository=repository
    )


def test_a_clean_index_is_permitted_and_a_private_file_or_a_secret_is_refused(
    repository: Path,
) -> None:
    (repository / "src" / "b.py").write_text("value = 2\n")
    git(repository, "add", "src/b.py")
    assert run(repository, "pre-commit") == (0, "")

    (repository / ".env").write_text("A=1\n")
    (repository / "notes.txt").write_text("-----BEGIN " + "PRIVATE KEY-----\nsecret\n")
    git(repository, "add", ".env", "notes.txt")
    code, text = run(repository, "pre-commit")

    assert code == errors.Refusal.exit_code
    assert "repository.private-document: .env" in text
    assert "repository.pem-private-key: notes.txt" in text
    assert text.endswith("change what is staged.\n")


def test_outgoing_commits_are_judged_by_message_and_tree_and_named(repository: Path) -> None:
    base = git(repository, "rev-parse", "HEAD").strip()
    (repository / "src" / "c.py").write_text("value = 3\n")
    git(repository, "add", "src/c.py")
    git(repository, "commit", "-q", "-m", "bad subject")
    bad = git(repository, "rev-parse", "HEAD").strip()
    (repository / ".env.local").write_text("A=1\n")
    git(repository, "add", ".env.local")
    git(repository, "commit", "-q", "-m", "chore(env): a private file")
    head = git(repository, "rev-parse", "HEAD").strip()

    code, text = run(repository, "pre-push", f"refs/heads/main {head} refs/heads/main {base}\n")
    created, _ = run(repository, "pre-push", f"refs/heads/main {base} refs/heads/main {NONE}\n")

    assert code == errors.Refusal.exit_code
    assert f"commit.subject-malformed: {bad[:12]}: bad subject" in text
    assert f"{head[:12]}: .env.local" in text
    assert text.endswith("rewrite the outgoing commits.\n")
    assert created == 0


def test_a_remote_commit_that_was_never_fetched_is_refused(repository: Path) -> None:
    head = git(repository, "rev-parse", "HEAD").strip()

    with pytest.raises(errors.Refusal) as refused:
        run(repository, "pre-push", f"refs/heads/main {head} refs/heads/main {'c' * 40}\n")

    assert refused.value.reason is refusals.RefusalReason.REPOSITORY_HISTORY_NOT_FETCHED


def test_the_installed_hooks_are_three_lines_each_and_a_foreign_hook_is_kept(
    repository: Path,
) -> None:
    processes = real_process.SubprocessRunner()
    filesystem = real_files.LocalFiles()

    written = hookinstall.install(processes, filesystem, repository)
    again = hookinstall.install(processes, filesystem, repository)

    assert [item.path.name for item in written] == ["commit-msg", "pre-commit", "pre-push"]
    assert written == again
    for item in written:
        lines = item.path.read_text().splitlines()
        assert lines[0] == "#!/bin/sh" and lines[1] == defaults.HOOK_MARKER
        assert lines[2].startswith("exec env PYTHONPATH=src uv run")
        assert lines[2].endswith(f'git-hook {item.path.name} "$@"') and len(lines) == 3
        assert item.path.stat().st_mode & 0o777 == 0o755
    (repository / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\necho mine\n")
    with pytest.raises(errors.Refusal) as refused:
        hookinstall.install(processes, filesystem, repository)
    assert refused.value.reason is refusals.RefusalReason.HOOK_FOREIGN
    assert (repository / ".git" / "hooks" / "pre-push").read_text() == "#!/bin/sh\necho mine\n"

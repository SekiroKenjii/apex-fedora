"""Reading Git through the process port: every answer parsed, every failure a refusal."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import fake_process
from apex.kernel import errors, refusals, treerows
from apex.workspace import gitreading, outgoing

REPO = Path("/repo")
LOCAL = "a" * 40
REMOTE = "b" * 40
NONE = "0" * 40


def git(*arguments: str) -> tuple[str, ...]:
    return ("git", "-C", str(REPO), *arguments)


def test_staged_rows_come_from_the_index_listing() -> None:
    processes = fake_process.ScriptedProcess({
        git("ls-files", "--stage", "-z"): fake_process.Reply(
            stdout=b"100644 abc 0\tsrc/a.py\x00100755 def 0\ttools/run.sh\x00"
        ),
    })

    rows = gitreading.staged_rows(processes, REPO)

    assert [(row.path.value, row.object_name) for row in rows] == [
        ("src/a.py", "abc"), ("tools/run.sh", "def"),
    ]
    assert rows[1].mode is treerows.EntryMode.EXECUTABLE


def test_sizes_come_from_one_batch_check_and_a_missing_object_is_refused() -> None:
    processes = fake_process.ScriptedProcess({
        git("cat-file", "--batch-check"): fake_process.Reply(
            stdout=b"abc blob 12\ndef blob 3000\n"
        ),
    })

    found = gitreading.sizes(processes, REPO, ["abc", "def"])
    with pytest.raises(errors.Refusal) as refused:
        gitreading.sizes(processes, REPO, ["abc", "ghi"])

    assert {name: size.value for name, size in found.items()} == {"abc": 12, "def": 3000}
    assert refused.value.reason is refusals.RefusalReason.HOOK_GIT_FAILED
    assert "ghi" in str(refused.value)
    assert gitreading.sizes(processes, REPO, []) == {}


def test_contents_come_from_one_batch_and_an_unread_object_is_refused() -> None:
    processes = fake_process.ScriptedProcess({
        git("cat-file", "--batch"): fake_process.Reply(
            stdout=b"abc blob 5\nhello\ndef blob 0\n\n"
        ),
    })

    found = gitreading.contents(processes, REPO, ["abc", "def"])
    with pytest.raises(errors.Refusal) as refused:
        gitreading.contents(processes, REPO, ["abc", "zzz"])

    assert found == {"abc": b"hello", "def": b""}
    assert refused.value.reason is refusals.RefusalReason.HOOK_CONTENT_UNREAD


def test_a_commit_s_message_is_what_follows_its_header() -> None:
    processes = fake_process.ScriptedProcess({
        git("cat-file", "commit", LOCAL): fake_process.Reply(
            stdout=b"tree t\nauthor a <a@b> 1 +0000\n\nfix(audio): the amplifier\n\nbody\n"
        ),
        git("cat-file", "commit", REMOTE): fake_process.Reply(stdout=b"tree t\n"),
    })

    assert gitreading.commit_message(processes, REPO, LOCAL) == (
        "fix(audio): the amplifier\n\nbody\n"
    )
    with pytest.raises(errors.Refusal) as refused:
        gitreading.commit_message(processes, REPO, REMOTE)
    assert refused.value.reason is refusals.RefusalReason.HOOK_GIT_FAILED


def test_outgoing_commits_are_the_range_no_remote_holds_and_a_deletion_asks_nothing() -> None:
    processes = fake_process.ScriptedProcess({
        git("cat-file", "-e", REMOTE): fake_process.Reply(),
        git("rev-list", "--reverse", LOCAL, f"^{REMOTE}", "--not", "--remotes"): (
            fake_process.Reply(stdout=b"c1\nc2\n")
        ),
        git("rev-list", "--reverse", LOCAL, "--not", "--remotes"): (
            fake_process.Reply(stdout=b"c3\n")
        ),
    })

    updated = gitreading.outgoing_commits(
        processes, REPO, outgoing.Update("refs/heads/x", LOCAL, "refs/heads/x", REMOTE)
    )
    created = gitreading.outgoing_commits(
        processes, REPO, outgoing.Update("refs/heads/x", LOCAL, "refs/heads/x", NONE)
    )
    deleted = gitreading.outgoing_commits(
        processes, REPO, outgoing.Update("refs/heads/x", NONE, "refs/heads/x", REMOTE)
    )

    assert updated == ("c1", "c2") and created == ("c3",) and deleted == ()
    assert len(processes.calls) == 3


def test_a_remote_commit_not_present_locally_is_refused_rather_than_subtracted() -> None:
    processes = fake_process.ScriptedProcess({
        git("cat-file", "-e", REMOTE): fake_process.Reply(exit_code=1, stderr=b"missing"),
    })

    with pytest.raises(errors.Refusal) as refused:
        gitreading.outgoing_commits(
            processes, REPO, outgoing.Update("refs/heads/x", LOCAL, "refs/heads/x", REMOTE)
        )

    assert refused.value.reason is refusals.RefusalReason.REPOSITORY_HISTORY_NOT_FETCHED


def test_a_failed_or_absent_git_is_a_refusal_carrying_its_words() -> None:
    processes = fake_process.ScriptedProcess({
        git("ls-files", "--stage", "-z"): fake_process.Reply(
            exit_code=128, stderr=b"fatal: not a git repository\n"
        ),
        git("ls-tree", "-rz", LOCAL): fake_process.Reply(missing=True),
    })

    with pytest.raises(errors.Refusal) as failed:
        gitreading.staged_rows(processes, REPO)
    with pytest.raises(errors.Refusal) as absent:
        gitreading.tree_rows(processes, REPO, LOCAL)

    assert failed.value.reason is refusals.RefusalReason.HOOK_GIT_FAILED
    assert "not a git repository" in str(failed.value)
    assert absent.value.reason is refusals.RefusalReason.HOOK_GIT_FAILED
    assert "not found" in str(absent.value)


def test_the_hooks_directory_is_where_git_says_it_is(tmp_path: Path) -> None:
    processes = fake_process.ScriptedProcess({
        ("git", "-C", str(tmp_path), "rev-parse", "--git-path", "hooks"): (
            fake_process.Reply(stdout=b".git/hooks\n")
        ),
        git("rev-parse", "--git-path", "hooks"): fake_process.Reply(stdout=b"/elsewhere/hooks\n"),
    })

    assert gitreading.hooks_directory(processes, tmp_path).path == tmp_path / ".git" / "hooks"
    assert gitreading.hooks_directory(processes, REPO).path == Path("/elsewhere/hooks")

"""The pre-commit and pre-push hooks over a scripted git: what they ask and what they find."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import fake_process
from apex.cli import hookkinds, hookspecs
from apex.kernel import errors, refusals

REPO = Path("/repo")
C1 = "1" * 40
C2 = "2" * 40
REMOTE = "b" * 40
NONE = "0" * 40


def git(*arguments: str) -> tuple[str, ...]:
    return ("git", "-C", str(REPO), *arguments)


def kind(name: str) -> hookspecs.HookKind:
    found = hookkinds.lookup(name)
    assert found is not None
    return found


def request(processes: fake_process.ScriptedProcess, stdin: str = "") -> hookspecs.HookRequest:
    return hookspecs.HookRequest(
        repository=REPO, arguments=(), standard_input=stdin, processes=processes
    )


def test_pre_commit_reads_the_index_once_the_sizes_once_and_the_small_blobs_once() -> None:
    processes = fake_process.ScriptedProcess(
        {
            git("ls-files", "--stage", "-z"): fake_process.Reply(
                stdout=b"100644 abc 0\tsrc/a.py\x00100644 abc 0\tsrc/b.py\x00"
            ),
            git("cat-file", "--batch-check"): fake_process.Reply(stdout=b"abc blob 10\n"),
            git("cat-file", "--batch"): fake_process.Reply(stdout=b"abc blob 10\nvalue = 1\n\n"),
        }
    )

    findings = kind("pre-commit").inspect(request(processes))

    assert findings == ()
    assert [tuple(call)[3:] for call in processes.calls] == [
        ("ls-files", "--stage", "-z"),
        ("cat-file", "--batch-check"),
        ("cat-file", "--batch"),
    ]


def test_pre_commit_refuses_a_private_file_and_a_secret_by_their_rules() -> None:
    processes = fake_process.ScriptedProcess(
        {
            git("ls-files", "--stage", "-z"): fake_process.Reply(
                stdout=b"100644 aaa 0\t.env\x00100644 bbb 0\tnotes.txt\x00"
            ),
            git("cat-file", "--batch-check"): fake_process.Reply(
                stdout=b"aaa blob 3\nbbb blob 32\n"
            ),
            git("cat-file", "--batch"): fake_process.Reply(
                stdout=b"aaa blob 3\nA=1\nbbb blob 32\n-----BEGIN "
                + b"PRIVATE KEY-----\nsecret\n\n"
            ),
        }
    )

    rules = sorted(str(item.rule) for item in kind("pre-commit").inspect(request(processes)))

    assert "repository.private-document" in rules
    assert "repository.pem-private-key" in rules


def test_pre_commit_stops_at_an_unmerged_index() -> None:
    processes = fake_process.ScriptedProcess(
        {git("ls-files", "--stage", "-z"): fake_process.Reply(stdout=b"100644 abc 1\tsrc/a.py\x00")}
    )

    with pytest.raises(errors.Refusal) as refused:
        kind("pre-commit").inspect(request(processes))

    assert refused.value.reason is refusals.RefusalReason.REPOSITORY_INDEX_UNMERGED


def outgoing(*commits: tuple[str, bytes, bytes]) -> fake_process.ScriptedProcess:
    """A remote-known update carrying the given commits, each with a message and one tree row."""
    replies = {
        git("cat-file", "-e", REMOTE): fake_process.Reply(),
        git("rev-list", "--reverse", C1, f"^{REMOTE}", "--not", "--remotes"): (
            fake_process.Reply(stdout=b"".join(f"{sha}\n".encode() for sha, _, _ in commits))
        ),
    }
    for sha, message, row in commits:
        replies[git("cat-file", "commit", sha)] = fake_process.Reply(
            stdout=b"tree t\nauthor a <a@b> 1 +0000\n\n" + message
        )
        replies[git("ls-tree", "-rz", sha)] = fake_process.Reply(stdout=row)
    replies[git("cat-file", "--batch-check")] = fake_process.Reply(stdout=b"abc blob 10\n")
    replies[git("cat-file", "--batch")] = fake_process.Reply(stdout=b"abc blob 10\nvalue = 1\n\n")
    return fake_process.ScriptedProcess(replies)


def test_pre_push_judges_every_outgoing_commit_s_message_and_tree_naming_the_commit() -> None:
    processes = outgoing(
        (C1, b"fix(audio): the amplifier\n", b"100644 blob abc\tsrc/a.py\x00"),
        (C2, b"bad subject\n", b"100644 blob abc\t.env\x00"),
    )
    line = f"refs/heads/x {C1} refs/heads/x {REMOTE}\n"

    findings = kind("pre-push").inspect(request(processes, line))

    named = sorted((str(item.rule), item.subject[:12]) for item in findings)
    assert named == [
        ("commit.subject-malformed", C2[:12]),
        ("repository.private-document", C2[:12]),
    ]


def test_pre_push_asks_git_nothing_for_a_branch_deletion_and_nothing_without_updates() -> None:
    processes = fake_process.ScriptedProcess()

    deletion = f"refs/heads/x {NONE} refs/heads/x {REMOTE}\n"
    assert kind("pre-push").inspect(request(processes, deletion)) == ()
    assert kind("pre-push").inspect(request(processes, "")) == ()
    assert processes.calls == []

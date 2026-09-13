"""The git-hook command: the rules' text and exit code, standard input only for pre-push."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import fake_files, fake_process
from apex.cli import commandspecs
from apex.cli.commands import githook_command
from apex.config import loader
from apex.kernel import errors, refusals, safepaths
from apex.wiring import contexts

REPOSITORY = Path(__file__).resolve().parents[3]


def context(processes: fake_process.ScriptedProcess | None) -> contexts.Context:
    return contexts.Context(
        settings=loader.load(host_file=None, environment={}),
        repository=safepaths.SourceRoot.adopt(REPOSITORY),
        root=None,
        environment={},
        bundle=lambda _root: pytest.fail("never asked"),
        processes=processes,
        filesystem=None if processes is None else fake_files.MemoryFiles(),
    )


def test_a_refused_message_comes_back_as_the_rules_text_with_their_exit_code(
    tmp_path: Path,
) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("update product\n")
    processes = fake_process.ScriptedProcess()

    reply = githook_command.run(commandspecs.Request(
        arguments=("commit-msg", str(message)), context=context(processes)
    ))

    assert reply.exit_code == errors.Refusal.exit_code and reply.document is None
    assert reply.narrative.startswith("BLOCKED: commit.subject-malformed: update product;")
    assert processes.calls == []


def test_pre_push_reads_standard_input_and_the_other_kinds_leave_it_alone(
    tmp_path: Path,
) -> None:
    reads: list[str] = []

    def read_input() -> str:
        reads.append("read")
        return f"refs/heads/x {'0' * 40} refs/heads/x {'b' * 40}\n"

    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("fix(audio): the amplifier\n")
    processes = fake_process.ScriptedProcess()

    pushed = githook_command.run(commandspecs.Request(
        arguments=("pre-push", "origin", "url"), context=context(processes), read_input=read_input
    ))
    committed = githook_command.run(commandspecs.Request(
        arguments=("commit-msg", str(message)), context=context(processes), read_input=read_input
    ))

    assert pushed.exit_code == 0 and pushed.narrative == ""
    assert committed.exit_code == 0
    assert reads == ["read"]


def test_a_context_without_repository_ports_cannot_answer_a_hook(tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("fix(audio): the amplifier\n")

    with pytest.raises(errors.PreconditionUnmet) as refused:
        githook_command.run(commandspecs.Request(
            arguments=("commit-msg", str(message)), context=context(None)
        ))

    assert refused.value.reason is refusals.RefusalReason.HOOK_PORTS_UNWIRED


def test_a_git_failure_is_the_reply_s_narrative_not_a_traceback() -> None:
    processes = fake_process.ScriptedProcess({
        ("git", "-C", str(REPOSITORY), "ls-files", "--stage", "-z"): fake_process.Reply(
            exit_code=128, stderr=b"fatal: bad index\n"
        ),
    })

    reply = githook_command.run(commandspecs.Request(
        arguments=("pre-commit",), context=context(processes)
    ))

    assert reply.exit_code == errors.Refusal.exit_code
    assert reply.narrative.startswith("hook.git-failed: git ls-files exited 128")

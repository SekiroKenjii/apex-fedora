"""Running a program. No shell is reachable and a deadline is required."""

from __future__ import annotations

import pytest

from apex.adapters.fakes import fake_process
from apex.kernel import commands, errors, safepaths, timing
from apex.ports import process


def short() -> timing.Deadline:
    return timing.Deadline(timing.Elapsed(30))


def test_a_successful_run_reports_its_output(processes: process.ProcessPort) -> None:
    completed = processes.run(
        commands.Argv.of("printf", "hello"), deadline=short(), limit=commands.OutputLimit.default()
    )

    assert completed.succeeded
    assert completed.stdout == b"hello"


def test_a_failing_run_reports_its_exit_code(processes: process.ProcessPort) -> None:
    completed = processes.run(
        commands.Argv.of("false"), deadline=short(), limit=commands.OutputLimit.default()
    )

    assert not completed.succeeded
    assert completed.exit_code != 0


def test_output_beyond_the_limit_is_cut_and_declared(processes: process.ProcessPort) -> None:
    completed = processes.run(
        commands.Argv.of("printf", "abcdefghij"),
        deadline=short(),
        limit=commands.OutputLimit(4),
    )

    assert completed.stdout == b"abcd"
    assert completed.truncated


def test_a_shell_metacharacter_is_an_argument_not_an_instruction(
    processes: process.ProcessPort,
) -> None:
    completed = processes.run(
        commands.Argv.of("printf", "%s", "; touch owned"),
        deadline=short(),
        limit=commands.OutputLimit.default(),
    )

    assert completed.stdout == b"; touch owned"


def test_an_absent_program_raises_a_port_failure(processes: process.ProcessPort) -> None:
    with pytest.raises(errors.PortFailure):
        processes.run(
            commands.Argv.of("apex-no-such-program"),
            deadline=short(),
            limit=commands.OutputLimit.default(),
        )


def test_a_run_that_exceeds_its_deadline_raises_a_port_failure(
    processes: process.ProcessPort,
) -> None:
    with pytest.raises(errors.PortFailure):
        processes.run(
            commands.Argv.of("sleep", "5"),
            deadline=timing.Deadline(timing.Elapsed(0.05)),
            limit=commands.OutputLimit.default(),
        )


def test_a_run_starts_in_the_directory_it_was_given(
    processes: process.ProcessPort, root: safepaths.RuntimeRoot
) -> None:
    inside = root.child("work")
    inside.path.mkdir()
    if isinstance(processes, fake_process.ScriptedProcess):
        processes.expect(("pwd",), fake_process.Reply(stdout=str(inside).encode() + b"\n"))

    completed = processes.run(
        commands.Argv.of("pwd"), deadline=short(), limit=commands.OutputLimit.default(), cwd=inside
    )

    assert completed.stdout.strip() == str(inside).encode()
    if isinstance(processes, fake_process.ScriptedProcess):
        assert processes.directories[-1] == inside


def test_a_run_with_a_transcript_writes_the_file_and_returns_no_output(
    processes: process.ProcessPort, root: safepaths.RuntimeRoot
) -> None:
    transcript = root.child("logs/run.log")

    completed = processes.run(
        commands.Argv.of("printf", "hello"),
        deadline=short(),
        limit=commands.OutputLimit.default(),
        transcript=transcript,
    )

    assert completed.succeeded
    assert completed.stdout == b""
    if isinstance(processes, fake_process.ScriptedProcess):
        assert processes.transcripts == [transcript]
    else:
        assert transcript.path.read_bytes() == b"hello"

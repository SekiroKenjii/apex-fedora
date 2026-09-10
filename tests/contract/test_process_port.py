"""Running a program. No shell is reachable and a deadline is required."""

from __future__ import annotations

import pytest

from apex.kernel import commands, errors, timing
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

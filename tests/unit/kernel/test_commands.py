"""A command is an argument vector. A shell string cannot be expressed."""

from __future__ import annotations

import pytest

from apex.kernel import commands, errors, quantities, safepaths, timing


def test_an_argument_vector_keeps_its_arguments_separate() -> None:
    argv = commands.Argv.of("qemu-img", "info", "--output=json")

    assert tuple(argv) == ("qemu-img", "info", "--output=json")


def test_an_argument_vector_accepts_a_checked_path(tmp_path) -> None:
    root = safepaths.RuntimeRoot.adopt(tmp_path)
    target = tmp_path / "disk.qcow2"
    target.write_bytes(b"")
    checked = safepaths.SafePath.regular_file(target, within=root)

    assert str(target) in tuple(commands.Argv.of("qemu-img", "info", checked))


def test_an_empty_argument_vector_is_refused() -> None:
    with pytest.raises(errors.Refusal):
        commands.Argv.of()


def test_a_guest_command_carries_a_deadline_and_an_output_limit() -> None:
    command = commands.GuestCommand(
        argv=commands.Argv.of("systemctl", "is-active", "gdm"),
        deadline=timing.Deadline(timing.Elapsed(30)),
        limit=commands.OutputLimit.default(),
    )

    assert command.deadline.budget.seconds == 30


def test_a_completed_run_reports_truncation_explicitly() -> None:
    completed = commands.CompletedRun(
        exit_code=0, stdout=b"x" * 10, stderr=b"", truncated=True
    )

    assert completed.truncated
    assert completed.succeeded


def test_a_completed_run_with_a_non_zero_code_did_not_succeed() -> None:
    assert not commands.CompletedRun(exit_code=2, stdout=b"", stderr=b"", truncated=False).succeeded


def test_the_default_output_limit_matches_the_guest_probes() -> None:
    assert commands.OutputLimit.default().value == 262144


def test_a_planned_command_renders_without_revealing_a_secret() -> None:
    planned = commands.PlannedCommand(
        argv=commands.Argv.of("ssh", "-p", str(quantities.TcpPort(22245))),
        redacted=("password",),
    )

    assert "password" not in planned.rendered

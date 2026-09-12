"""A remote script renders to exactly the words its steps hold, quoted once."""

from __future__ import annotations

import pytest

from apex.kernel import errors, safepaths
from apex.ports import guestshell


def test_steps_are_joined_by_and_and_quoted_by_the_shell_rules() -> None:
    script = guestshell.RemoteScript.of(
        guestshell.Step.of("cd", "/var/tmp/apex-a"),
        guestshell.Step.of("bash", "-c", "bash guest/bootstrap.sh && bash guest/build.sh"),
    )

    assert script.rendered() == (
        "cd /var/tmp/apex-a && bash -c 'bash guest/bootstrap.sh && bash guest/build.sh'"
    )


def test_a_locked_step_wraps_the_whole_script_under_the_guest_lock() -> None:
    inner = guestshell.RemoteScript.of(
        guestshell.Step.of("bash", "guest/bootstrap.sh"),
        guestshell.Step.of("bash", "guest/build.sh", "fedora", "image"),
    )

    locked = inner.under_lock(safepaths.RemotePath("/run/apex-build.lock"))

    assert locked.rendered() == (
        "sudo flock -n /run/apex-build.lock bash -c "
        "'bash guest/bootstrap.sh && bash guest/build.sh fedora image'"
    )


def test_the_two_admitted_shell_forms_render_after_the_command() -> None:
    step = guestshell.Step(
        guestshell.Step.of("sudo", "chown", "-R", "builder:builder", "/var/tmp/x/output").argv,
        quiet_errors=True,
        tolerated=True,
    )

    assert step.rendered() == "sudo chown -R builder:builder /var/tmp/x/output 2>/dev/null || true"


def test_an_empty_script_is_refused() -> None:
    with pytest.raises(errors.Refusal):
        guestshell.RemoteScript.of()

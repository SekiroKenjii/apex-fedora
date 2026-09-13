"""A hook the rules do not answer is refused under its own reason; one they do is reported."""

from __future__ import annotations

from pathlib import Path

import pytest

from apex.adapters.fakes import fake_process
from apex.cli import hookdispatch, hookkinds
from apex.kernel import errors, refusals


def test_an_unknown_hook_kind_is_a_hook_fault_not_a_settings_fault() -> None:
    with pytest.raises(errors.PreconditionUnmet) as raised:
        hookdispatch.run(["post-checkout"], "", processes=fake_process.ScriptedProcess())

    assert raised.value.reason is refusals.RefusalReason.HOOK_KIND_UNKNOWN


def test_a_missing_hook_kind_is_reported_the_same_way() -> None:
    with pytest.raises(errors.PreconditionUnmet) as raised:
        hookdispatch.run([], "", processes=fake_process.ScriptedProcess())

    assert raised.value.reason is refusals.RefusalReason.HOOK_KIND_UNKNOWN


def test_the_three_hooks_git_runs_are_the_kinds_the_rules_answer() -> None:
    assert hookkinds.names() == ("commit-msg", "pre-commit", "pre-push")


def test_a_refused_message_is_reported_with_the_kind_s_own_footer_unless_one_is_given(
    tmp_path: Path,
) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("update product\n")
    processes = fake_process.ScriptedProcess()

    code, text = hookdispatch.run(["commit-msg", str(message)], "", processes=processes)
    _, given = hookdispatch.run(
        ["commit-msg", str(message)], "", "Footer given.", processes=processes
    )

    assert code == errors.Refusal.exit_code
    assert text.startswith("BLOCKED: commit.subject-malformed: update product;")
    assert text.endswith("the rule that refused is named above; change the message.\n")
    assert given.endswith("Footer given.\n")
    assert processes.calls == []


def test_a_permitted_message_is_silent(tmp_path: Path) -> None:
    message = tmp_path / "COMMIT_EDITMSG"
    message.write_text("fix(audio): initialise the amplifier\n")

    assert hookdispatch.run(
        ["commit-msg", str(message)], "", processes=fake_process.ScriptedProcess()
    ) == (0, "")

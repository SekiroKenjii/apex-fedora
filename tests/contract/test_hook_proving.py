"""The three git checks proven over disposable repositories through the real Git.

The hooks answer as Git would call them, and every question each check states gets the
answer the rules must give. A hook that permits everything, or one that refuses instead of
answering, is caught by the same report.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from apex.adapters.real import real_files, real_process
from apex.cli import hookkinds, hookspecs
from apex.kernel import errors, refusals, safepaths, verdicts
from apex.workspace import hookproving, rulespecs

PROCESSES = real_process.SubprocessRunner()


def through_the_hooks(
    hook: str, repository: Path, arguments: Sequence[str], standard_input: str
) -> Sequence[rulespecs.Finding]:
    kind = hookkinds.lookup(hook)
    assert kind is not None
    return kind.inspect(
        hookspecs.HookRequest(
            repository=repository,
            arguments=tuple(arguments),
            standard_input=standard_input,
            processes=PROCESSES,
        )
    )


def permitting(
    hook: str, repository: Path, arguments: Sequence[str], standard_input: str
) -> Sequence[rulespecs.Finding]:
    return ()


def refusing(
    hook: str, repository: Path, arguments: Sequence[str], standard_input: str
) -> Sequence[rulespecs.Finding]:
    raise errors.Refusal(refusals.RefusalReason.HOOK_GIT_FAILED, subject=hook)


def bench(tmp_path: Path, inspect: hookproving.Inspect = through_the_hooks) -> hookproving.Bench:
    tmp_path.chmod(0o700)
    return hookproving.Bench(
        processes=PROCESSES,
        filesystem=real_files.LocalFiles(),
        scratch=safepaths.SafePath(tmp_path),
        inspect=inspect,
    )


def answers(proven: hookproving.Proven) -> list[tuple[str, bool]]:
    listed = proven.observations["answers"]
    assert isinstance(listed, list)
    return [(str(item["question"]), bool(item["met"])) for item in listed]  # type: ignore[index]


@pytest.mark.parametrize(
    ("prover", "check", "count"),
    [
        (hookproving.commit_policy, "git.commit-policy", 7),
        (hookproving.private_stage, "git.private-stage", 7),
        (hookproving.outgoing_history, "git.outgoing-history", 4),
    ],
)
def test_every_question_of_a_check_gets_the_answer_the_rules_must_give(
    tmp_path: Path, prover: hookproving.Prover, check: str, count: int
) -> None:
    proven = prover(bench(tmp_path))

    assert proven.verdict is verdicts.PASSED
    assert proven.observations["check"] == check
    assert len(answers(proven)) == count
    assert all(met for _, met in answers(proven))


def test_the_outgoing_history_names_both_faults_and_the_unfetched_remote(tmp_path: Path) -> None:
    proven = hookproving.outgoing_history(bench(tmp_path))

    listed = proven.observations["answers"]
    assert isinstance(listed, list)
    first = listed[0]
    assert isinstance(first, dict)
    assert set(first["expected"]) <= set(first["found"])  # type: ignore[arg-type]
    last = listed[-1]
    assert isinstance(last, dict)
    assert last["found"] == ["repository.history-not-fetched"]


def test_a_hook_that_permits_everything_fails_every_refusing_question(tmp_path: Path) -> None:
    proven = hookproving.private_stage(bench(tmp_path, permitting))

    assert proven.verdict is verdicts.FAILED
    assert answers(proven) == [
        ("a clean file", True),
        ("a private document", False),
        ("a private key", False),
        ("a local-only document under another name", False),
        ("an opaque binary", False),
        ("a symlink entry", False),
        ("a submodule entry", False),
    ]


def test_a_hook_that_refuses_instead_of_answering_is_recorded_by_its_reason(tmp_path: Path) -> None:
    proven = hookproving.commit_policy(bench(tmp_path, refusing))

    listed = proven.observations["answers"]
    assert isinstance(listed, list)
    assert all(item["found"] == ["hook.git-failed"] for item in listed)  # type: ignore[index]
    assert proven.verdict is verdicts.FAILED


def test_a_git_command_that_fails_is_a_refusal_naming_the_command(tmp_path: Path) -> None:
    made = bench(tmp_path)
    repository = made.repository("failing")

    with pytest.raises(errors.Refusal) as refused:
        made.git(repository, "rev-parse", "--verify", "no-such-ref")

    assert refused.value.reason is refusals.RefusalReason.HOOK_GIT_FAILED
    assert refused.value.subject.startswith("git rev-parse exited ")


def test_the_repositories_carry_a_fixture_identity_and_none_of_the_operators(
    tmp_path: Path,
) -> None:
    made = bench(tmp_path)
    repository = made.repository("identity")

    assert made.git(repository, "log", "-1", "--format=%an <%ae>") == "apex <apex@localhost>"
    assert made.git(repository, "log", "-1", "--format=%s") == hookproving.FIRST_SUBJECT

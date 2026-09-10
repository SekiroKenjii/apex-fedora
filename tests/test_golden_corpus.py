from __future__ import annotations

import json
from pathlib import Path

import pytest

REPOSITORY = Path(__file__).resolve().parents[1]
CORPUS = REPOSITORY / "tests" / "golden" / "commands.json"
MUTATING = frozenset({"write", "rename", "copy", "mkdir", "remove"})


def corpus() -> list[dict[str, object]]:
    return json.loads(CORPUS.read_text())["invocations"]


def test_the_corpus_is_committed_and_populated() -> None:
    invocations = corpus()

    assert len(invocations) >= 70
    assert {str(item["tier"]) for item in invocations} == {"pure", "refusal"}


def test_every_slug_is_unique() -> None:
    slugs = [str(item["slug"]) for item in corpus()]

    assert len(slugs) == len(set(slugs))


def test_every_subcommand_has_a_help_capture() -> None:
    from migration import golden_corpus

    captured = {str(item["slug"]) for item in corpus()}

    for name in golden_corpus.SUBCOMMANDS:
        assert f"help-{name}" in captured


def test_no_capture_retains_an_absolute_host_path() -> None:
    for item in corpus():
        for field in ("stdout", "stderr"):
            text = str(item[field])
            assert "/home/" not in text, f"{item['slug']} leaked a home path"


def test_refusals_exit_non_zero() -> None:
    for item in corpus():
        if str(item["tier"]) == "refusal":
            assert item["exit_code"] != 0, f"{item['slug']} refused but exited zero"


def test_pure_invocations_exit_zero() -> None:
    for item in corpus():
        if str(item["tier"]) == "pure":
            assert item["exit_code"] == 0, f"{item['slug']} was expected to succeed"


@pytest.mark.parametrize(
    "slug",
    [
        "select-candidate-bad-id",
        "verify-artifact-missing-directory",
        "installer-logs-prepare-with-run",
        "installer-logs-collect-without-token",
        "record-unknown-check",
        "record-hardware-from-vm",
        "record-pass-without-proof",
    ],
)
def test_known_refusals_create_the_runtime_root_before_refusing(slug: str) -> None:
    """Pin today's behaviour so the restructure changes it deliberately.

    `state_dir()` creates the root unconditionally, so a command that refuses has
    already written to the host. The target architecture refuses before any effect.
    """
    item = next(entry for entry in corpus() if entry["slug"] == slug)
    mutations = [event for event in item["effects"] if event["kind"] in MUTATING]

    assert mutations == [{"kind": "mkdir", "target": "<root>"}]


def test_readiness_persists_derived_state_before_refusing() -> None:
    item = next(entry for entry in corpus() if entry["slug"] == "readiness-blocked")
    kinds = [event["kind"] for event in item["effects"]]

    assert item["exit_code"] == 2
    assert "write" in kinds
    assert "rename" in kinds


def test_most_invocations_have_no_effects_at_all() -> None:
    quiet = [item for item in corpus() if not item["effects"]]

    assert len(quiet) >= 60


def test_the_commit_guard_rejects_a_co_author_trailer() -> None:
    item = next(entry for entry in corpus() if entry["slug"] == "commit-msg-with-co-author")

    assert item["exit_code"] == 2
    assert "Conventional Commit" in str(item["stderr"])


def test_the_commit_guard_accepts_the_documented_subject() -> None:
    item = next(entry for entry in corpus() if entry["slug"] == "commit-msg-valid")

    assert item["exit_code"] == 0


@pytest.mark.golden
def test_replaying_every_command_reproduces_the_corpus(tmp_path: Path) -> None:
    from migration import golden_corpus

    assert golden_corpus.main(["verify", "--scratch", str(tmp_path)]) == 0

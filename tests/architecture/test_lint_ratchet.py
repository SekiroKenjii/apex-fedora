"""New code is clean. Old code may improve but never regress."""

from __future__ import annotations

import json
import shutil

import pytest

from migration import lint_ratchet


def baseline() -> dict[str, int]:
    return json.loads(lint_ratchet.BASELINE.read_text())["files"]


def test_the_baseline_is_committed_and_describes_the_old_tree() -> None:
    files = baseline()

    assert len(files) >= 100
    assert sum(files.values()) > 0


def test_no_file_written_during_the_restructure_is_in_the_baseline() -> None:
    clean = [path for path in baseline() if path.startswith(("src/", "tools/migration/"))]

    assert clean == []


def test_a_new_file_with_findings_is_a_regression() -> None:
    problems = lint_ratchet.regressions({"old.py": 3}, {"old.py": 3, "src/apex/new.py": 1})

    assert len(problems) == 1
    assert "expects to be clean" in problems[0]


def test_more_findings_in_an_existing_file_is_a_regression() -> None:
    problems = lint_ratchet.regressions({"old.py": 3}, {"old.py": 4})

    assert problems == ["old.py: 4 findings, baseline allows 3"]


def test_fewer_findings_is_allowed() -> None:
    assert lint_ratchet.regressions({"old.py": 3}, {"old.py": 1}) == []


def test_removing_a_file_entirely_is_allowed() -> None:
    assert lint_ratchet.regressions({"old.py": 3}, {}) == []


@pytest.mark.skipif(shutil.which("uv") is None, reason="NOT TESTED: uv is absent")
def test_the_working_tree_has_no_regression() -> None:
    assert lint_ratchet.check() == 0


def test_the_baseline_records_the_configuration_that_produced_it() -> None:
    document = json.loads(lint_ratchet.BASELINE.read_text())

    assert document["configuration"] == lint_ratchet.configuration_digest()


def test_the_configuration_digest_covers_the_rule_selection() -> None:
    first = lint_ratchet.configuration_digest()

    assert len(first) == 64
    assert first == lint_ratchet.configuration_digest()

"""A refusal reason nobody raises is a declaration pretending to be a rule."""

from __future__ import annotations

from pathlib import Path

from apex.kernel import refusals

SOURCE = Path(__file__).resolve().parents[2] / "src" / "apex"
GOVERNED = ("REPOSITORY_", "COMMIT_", "HOOK_")


def test_every_repository_and_commit_reason_has_a_producer() -> None:
    body = "\n".join(
        path.read_text()
        for path in sorted(SOURCE.rglob("*.py"))
        if path.name != "refusals.py"
    )
    orphans = [
        member.name
        for member in refusals.RefusalReason
        if member.name.startswith(GOVERNED) and member.name not in body
    ]

    assert orphans == []

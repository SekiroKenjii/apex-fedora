"""Which commits a push adds, and the two update shapes that cannot be answered."""

from __future__ import annotations

import pytest

from apex.kernel import errors, refusals
from apex.workspace import outgoing

ZERO = "0" * 40
LOCAL = "a" * 40
REMOTE = "b" * 40


def test_a_branch_deletion_selects_nothing() -> None:
    update = outgoing.parse_update(f"refs/heads/x {ZERO} refs/heads/x {REMOTE}")

    assert update.deletes_the_branch
    assert outgoing.revision_arguments(update, remote_is_known=True) == ()


def test_a_new_branch_selects_its_whole_history() -> None:
    update = outgoing.parse_update(f"refs/heads/x {LOCAL} refs/heads/x {ZERO}")

    assert outgoing.revision_arguments(update, remote_is_known=True) == (LOCAL,)


def test_a_known_remote_subtracts_what_it_already_has() -> None:
    update = outgoing.parse_update(f"refs/heads/x {LOCAL} refs/heads/x {REMOTE}")

    assert outgoing.revision_arguments(update, remote_is_known=True) == (LOCAL, f"^{REMOTE}")


def test_an_unfetched_remote_is_refused_rather_than_treated_as_empty() -> None:
    """Subtracting nothing would offer the whole branch and look like a hang."""
    update = outgoing.parse_update(f"refs/heads/x {LOCAL} refs/heads/x {REMOTE}")

    with pytest.raises(errors.Refusal) as raised:
        outgoing.revision_arguments(update, remote_is_known=False)

    assert raised.value.reason is refusals.RefusalReason.REPOSITORY_HISTORY_NOT_FETCHED


def test_a_malformed_update_line_is_a_typed_refusal() -> None:
    with pytest.raises(errors.Refusal) as raised:
        outgoing.parse_update("refs/heads/x only-three-fields here")

    assert raised.value.reason is refusals.RefusalReason.REPOSITORY_UPDATE_LINE_MALFORMED


def test_blank_lines_between_updates_are_ignored() -> None:
    raw = f"refs/heads/x {LOCAL} refs/heads/x {ZERO}\n\n"

    assert len(outgoing.updates(raw)) == 1

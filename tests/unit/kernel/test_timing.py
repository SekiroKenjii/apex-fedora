"""Waiting is injectable, so the fast suite never sleeps."""

from __future__ import annotations

import pytest

from apex.kernel import errors, timing


def test_an_elapsed_span_is_non_negative() -> None:
    with pytest.raises(errors.Refusal):
        timing.Elapsed(-1)


def test_a_deadline_is_expressed_as_a_budget() -> None:
    assert timing.Deadline(timing.Elapsed(240)).budget.seconds == 240


def test_a_deadline_reports_whether_an_instant_has_passed_it() -> None:
    deadline = timing.Deadline(timing.Elapsed(10), started=timing.Instant(100))

    assert not deadline.expired_at(timing.Instant(109))
    assert deadline.expired_at(timing.Instant(111))


def test_exponential_backoff_grows_and_then_holds_at_its_ceiling() -> None:
    backoff = timing.Backoff.exponential(
        first=timing.Elapsed(0.05), ceiling=timing.Elapsed(2), factor=2
    )
    delays = [backoff.delay(attempt).seconds for attempt in range(8)]

    assert delays[0] == pytest.approx(0.05)
    assert delays == sorted(delays)
    assert delays[-1] == pytest.approx(2)


def test_a_wait_policy_names_its_budget_and_its_backoff() -> None:
    policy = timing.WaitPolicy(
        deadline=timing.Deadline(timing.Elapsed(240)),
        backoff=timing.Backoff.exponential(
            first=timing.Elapsed(0.05), ceiling=timing.Elapsed(2), factor=2
        ),
        description="the guest answers on the monitor socket",
    )

    assert policy.deadline.budget.seconds == 240
    assert policy.description


def test_a_policy_without_a_description_is_a_declaration_fault() -> None:
    with pytest.raises(errors.RegistrationError):
        timing.WaitPolicy(
            deadline=timing.Deadline(timing.Elapsed(1)),
            backoff=timing.Backoff.exponential(
                first=timing.Elapsed(0.05), ceiling=timing.Elapsed(2), factor=2
            ),
            description="",
        )
